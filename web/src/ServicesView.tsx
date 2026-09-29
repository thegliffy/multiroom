import { useCallback, useEffect, useState } from "react";
import {
  api,
  type ServiceHost,
  type ServiceSuggestion,
} from "./api";

function stateClass(state: string) {
  if (state === "active") return "";
  if (state === "failed") return "off";
  return "soft";
}

export default function ServicesView({
  onBack,
  onError,
}: {
  onBack: () => void;
  onError: (msg: string | null) => void;
}) {
  const [hosts, setHosts] = useState<ServiceHost[]>([]);
  const [suggestions, setSuggestions] = useState<ServiceSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  const refresh = useCallback(async () => {
    const data = await api.services();
    setHosts(data.hosts);
    setSuggestions(data.suggestions || []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh();
      } catch (e) {
        if (!cancelled) onError(e instanceof Error ? e.message : String(e));
      }
    })();
    const t = setInterval(() => {
      refresh().catch(() => undefined);
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [refresh, onError]);

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    onError(null);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="services-panel">
      <div className="services-head">
        <div>
          <button type="button" className="back" onClick={onBack}>
            ← Back to library
          </button>
          <h2>Services</h2>
          <p className="services-lead">
            One place for the hub stack and every Pi agent — check health, restart rooms, add more Pis.
          </p>
        </div>
        <button type="button" className="btn ghost" disabled={busy} onClick={() => withBusy(refresh)}>
          Refresh
        </button>
      </div>

      <div className="services-grid">
        {hosts.map((host) => (
          <article className="host-card" key={host.id}>
            <header className="host-head">
              <div>
                <h3>{host.name}</h3>
                <small>
                  {host.kind === "local"
                    ? "This host"
                    : host.hostname
                      ? host.hostname
                      : host.url || host.id}
                  {host.reachable === false ? " · unreachable" : ""}
                </small>
              </div>
              <span className={`badge ${host.reachable === false ? "off" : ""}`}>
                {host.kind === "local" ? "local" : host.reachable ? "online" : "offline"}
              </span>
            </header>
            {host.error ? <p className="host-error">{host.error}</p> : null}
            <ul className="service-list">
              {(host.services || []).map((svc) => (
                <li key={svc.id}>
                  <div className="service-copy">
                    <strong>{svc.name}</strong>
                    <small>
                      {svc.id}
                      {svc.detail ? ` · ${svc.detail}` : ""}
                    </small>
                  </div>
                  <div className="service-actions">
                    <span className={`badge ${stateClass(svc.state)}`}>{svc.state}</span>
                    {(svc.actions || []).map((action) => (
                      <button
                        key={action}
                        type="button"
                        className={action === "stop" ? "svc-btn danger" : "svc-btn"}
                        disabled={busy || !svc.controllable}
                        onClick={() =>
                          withBusy(async () => {
                            const data = await api.serviceAction(host.id, svc.id, action);
                            setHosts(data.hosts);
                            setSuggestions(data.suggestions || []);
                          })
                        }
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                </li>
              ))}
              {!host.services?.length && !host.error ? (
                <li className="empty-row">No services reported.</li>
              ) : null}
            </ul>
            {host.kind === "agent" && host.id !== "hub" ? (
              <button
                type="button"
                className="svc-btn danger ghost-wide"
                disabled={busy}
                onClick={() =>
                  withBusy(async () => {
                    await api.removeAgent(host.id);
                    await refresh();
                  })
                }
              >
                Remove Pi from hub
              </button>
            ) : null}
          </article>
        ))}
      </div>

      <article className="host-card add-agent">
        <h3>Add a Pi agent</h3>
        <p className="services-lead">
          Point at the pairing UI (<code>:8190</code>) so this hub can manage its systemd services.
        </p>
        <div className="add-agent-row">
          <label>
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Living room Pi"
            />
          </label>
          <label>
            URL
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://10.0.0.20:8190"
            />
          </label>
          <button
            type="button"
            className="btn"
            disabled={busy || !url.trim()}
            onClick={() =>
              withBusy(async () => {
                await api.addAgent(name.trim() || url.trim(), url.trim());
                setName("");
                setUrl("");
                await refresh();
              })
            }
          >
            Add
          </button>
        </div>
        {suggestions.length ? (
          <div className="suggestions">
            <h4>Seen on Snapcast</h4>
            {suggestions.map((s) => (
              <button
                key={s.url}
                type="button"
                className="suggestion"
                disabled={busy}
                onClick={() =>
                  withBusy(async () => {
                    await api.addAgent(s.name, s.url);
                    await refresh();
                  })
                }
              >
                Add {s.name} · {s.url}
              </button>
            ))}
          </div>
        ) : null}
      </article>
    </section>
  );
}
