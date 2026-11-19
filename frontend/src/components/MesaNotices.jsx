import { useCallback, useEffect, useRef, useState } from 'react';
import './MesaNotices.css';

const MAX_NOTICES = 3;
const DEFAULT_DURATION = 5000;

function normalizeNotice(input, options = {}) {
  const value = typeof input === 'string' ? { text: input } : (input || {});
  const text = value.text ?? value.message ?? options.text ?? options.message ?? '';
  const requestedType = value.type ?? value.severity ?? options.type ?? options.severity ?? 'info';
  const type = ['error', 'success', 'info'].includes(requestedType) ? requestedType : 'info';
  return {
    text: String(text).trim(),
    type,
    key: value.key ?? options.key ?? `${type}:${String(text).trim()}`,
    duration: value.autoHideDuration ?? options.autoHideDuration ?? DEFAULT_DURATION,
  };
}

export function useMesaNotices() {
  const [notices, setNotices] = useState([]);
  const nextId = useRef(0);
  const timers = useRef(new Map());
  const activeKeys = useRef(new Map());

  const dismiss = useCallback((id) => {
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
    activeKeys.current.forEach((activeId, key) => {
      if (activeId === id) activeKeys.current.delete(key);
    });
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const notify = useCallback((input, options = {}) => {
    const normalized = normalizeNotice(input, options);
    if (!normalized.text) return undefined;
    const existingId = activeKeys.current.get(normalized.key);
    const duration = Number(normalized.duration);
    const timeoutDuration = Math.min(DEFAULT_DURATION, Number.isFinite(duration) && duration > 0 ? duration : DEFAULT_DURATION);
    if (existingId) {
      const previousTimer = timers.current.get(existingId);
      if (previousTimer) window.clearTimeout(previousTimer);
      timers.current.set(existingId, window.setTimeout(() => dismiss(existingId), timeoutDuration));
      return existingId;
    }

    const id = `mesa-notice-${Date.now()}-${nextId.current += 1}`;
    const notice = { id, text: normalized.text, type: normalized.type };
    activeKeys.current.set(normalized.key, id);
    setNotices((current) => {
      const next = [...current, notice];
      const dropped = next.length > MAX_NOTICES ? next.slice(0, next.length - MAX_NOTICES) : [];
      dropped.forEach((item) => {
        const timer = timers.current.get(item.id);
        if (timer) window.clearTimeout(timer);
        timers.current.delete(item.id);
        activeKeys.current.forEach((activeId, key) => {
          if (activeId === item.id) activeKeys.current.delete(key);
        });
      });
      return next.slice(-MAX_NOTICES);
    });
    timers.current.set(id, window.setTimeout(() => dismiss(id), timeoutDuration));
    return id;
  }, [dismiss]);

  useEffect(() => () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current.clear();
    activeKeys.current.clear();
  }, []);

  return { notices, notify, dismiss };
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="m3 3 10 10M13 3 3 13" />
    </svg>
  );
}

export function MesaNotices({ notices = [], dismiss }) {
  if (!notices.length) return null;
  return (
    <div className="mesa-notices-region" data-testid="mesa-notice-region" aria-label="Avisos de la estación">
      {notices.slice(-MAX_NOTICES).map((notice) => {
        const type = notice.type || 'info';
        const role = type === 'error' ? 'alert' : 'status';
        return (
          <div key={notice.id} className={`mesa-notice-toast ${type}`} role={role} aria-live={type === 'error' ? 'assertive' : 'polite'}>
            <span className="mesa-notice-toast-text">{notice.text ?? notice.message}</span>
            <button type="button" className="mesa-notice-close" aria-label="Cerrar notificación" onClick={() => dismiss?.(notice.id)}>
              <CloseIcon />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export default MesaNotices;
