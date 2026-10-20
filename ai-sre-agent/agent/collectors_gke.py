"""GKE collector: pods, deployment health, warning events, crash logs."""
from .models import Finding

BAD_WAITING = {
    "ImagePullBackOff": "critical",
    "ErrImagePull": "critical",
    "CrashLoopBackOff": "critical",
    "CreateContainerConfigError": "critical",
    "CreateContainerError": "critical",
    "InvalidImageName": "critical",
}


def _load():
    from kubernetes import config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()


def collect(namespace: str, deployment: str) -> list[Finding]:
    from kubernetes import client
    _load()
    v1, apps = client.CoreV1Api(), client.AppsV1Api()
    out: list[Finding] = []

    # --- Deployment level
    try:
        d = apps.read_namespaced_deployment(deployment, namespace)
        want = d.spec.replicas or 0
        ready = d.status.ready_replicas or 0
        images = [c.image for c in d.spec.template.spec.containers]
        if ready < want:
            out.append(Finding(
                "gke", "DeploymentDegraded", "critical",
                f"{deployment}: {ready}/{want} replicas ready",
                {"images": images, "generation": d.metadata.generation,
                 "conditions": [f"{c.type}={c.status}:{c.reason}" for c in (d.status.conditions or [])]},
            ))
    except Exception as e:
        out.append(Finding("gke", "DeploymentMissing", "critical",
                           f"Cannot read deployment {deployment}: {e}"))

    # --- Pod level
    for p in v1.list_namespaced_pod(namespace).items:
        name = p.metadata.name
        for cs in (p.status.container_statuses or []):
            w = cs.state.waiting
            t = cs.last_state.terminated
            if w and w.reason in BAD_WAITING:
                f = Finding("gke", w.reason, BAD_WAITING[w.reason],
                            f"Pod {name} container {cs.name}: {w.reason}",
                            {"pod": name, "image": cs.image, "message": (w.message or "")[:300],
                             "restarts": cs.restart_count})
                if w.reason == "CrashLoopBackOff":
                    f.details["logs_tail"] = _logs(v1, namespace, name, cs.name)
                out.append(f)
            elif t and t.reason == "OOMKilled":
                out.append(Finding("gke", "OOMKilled", "critical",
                                   f"Pod {name} container {cs.name} was OOMKilled",
                                   {"pod": name, "restarts": cs.restart_count}))
        if p.status.phase == "Pending":
            for c in (p.status.conditions or []):
                if c.type == "PodScheduled" and c.status == "False":
                    out.append(Finding("gke", "Unschedulable", "warning",
                                       f"Pod {name} pending: {c.reason}",
                                       {"pod": name, "message": (c.message or "")[:300]}))

    # --- Recent warning events
    try:
        evs = v1.list_namespaced_event(namespace, field_selector="type=Warning").items
        evs.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp, reverse=True)
        for e in evs[:5]:
            out.append(Finding("gke", "WarningEvent", "info",
                               f"{e.involved_object.kind}/{e.involved_object.name}: {e.reason}",
                               {"message": (e.message or "")[:300], "count": e.count}))
    except Exception:
        pass
    return out


def _logs(v1, ns, pod, container, tail=25):
    try:
        return v1.read_namespaced_pod_log(pod, ns, container=container, previous=True,
                                          tail_lines=tail)
    except Exception:
        try:
            return v1.read_namespaced_pod_log(pod, ns, container=container, tail_lines=tail)
        except Exception as e:
            return f"(no logs: {e})"
