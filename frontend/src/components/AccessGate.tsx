import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { accessKey, api, AUTH_EVENT } from "../services/api";

/** Asks for the access key when the backend answers 401. The key lives in sessionStorage for this tab only. */
export function AccessGate({ children }: { children: ReactNode }) {
  const [needed, setNeeded] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const on = () => setNeeded(true);
    window.addEventListener(AUTH_EVENT, on);
    return () => window.removeEventListener(AUTH_EVENT, on);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    accessKey.set(value);
    try {
      await api.scans(1);
      window.location.reload();
    } catch {
      accessKey.clear();
      setError("That key was not accepted.");
      setBusy(false);
    }
  };

  if (!needed) return <>{children}</>;
  return (
    <div className="gate">
      <form className="card gate-card" onSubmit={submit}>
        <h1>Viona</h1>
        <p className="muted">Real-time network threat detection. Enter the access key to continue.</p>
        <label className="field">Access key
          <input type="password" autoFocus autoComplete="current-password" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        {error && <div className="err" role="alert">{error}</div>}
        <button className="btn primary" disabled={busy || value === ""}>Continue</button>
      </form>
    </div>
  );
}
