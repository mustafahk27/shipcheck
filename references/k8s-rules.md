# Kubernetes rules

## HIGH — `no-resource-limits`: containers without CPU/memory limits

**Detects:** a manifest with `containers:` but no `resources:` / `limits:` block.

**Why it kills prod:** A pod with no limits can consume the entire node. One
memory leak evicts every neighbor (the kubelet kills *other* pods to reclaim
memory), turning one bad deploy into a cluster-wide incident. Without requests,
the scheduler also has no idea where the pod fits.

**Fix:**
```yaml
spec:
  containers:
    - name: api
      image: myapp:1.4.2
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
        limits:
          cpu: "1"
          memory: 512Mi
```

**Guidance:**
- Set `requests` to typical usage, `limits` to tolerable peak.
- Common practice: set memory `limits` == `requests` (avoids overcommit OOM
  surprises); leave CPU limit off or generous — CPU throttling hurts latency,
  memory overrun kills pods.
- Enforce cluster-wide with a `LimitRange` per namespace so unlimited pods
  can't be created at all.

## Also worth checking manually (not yet automated)

- `livenessProbe` / `readinessProbe` missing — same class of problem as the
  Docker HEALTHCHECK rule.
- `image: ...:latest` in pod specs — caught by shipcheck's secret/latest scan
  when present in the manifest.
- `securityContext.runAsNonRoot: true` absent.
