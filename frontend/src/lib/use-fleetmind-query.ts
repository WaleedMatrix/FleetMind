"use client";

import { useEffect, useState } from "react";
import { FleetMindApiError, fleetMindRequest } from "./api";

type LoadState<T> = { path: string; data: T | null; error: string | null; status?: number; pending: boolean };
type QueryOptions = { pollMs?: number; delay?: number; revision?: number };

export function useFleetMindQuery<T>(
  path: string | null, { pollMs, delay = 0, revision = 0 }: QueryOptions = {},
) {
  const [state, setState] = useState<LoadState<T> | null>(null);

  useEffect(() => {
    if (path === null) return;
    const target = path;
    let request: AbortController | null = null;

    async function load() {
      if (request) return;
      const controller = new AbortController();
      request = controller;
      setState((previous) => ({
        path: target, data: previous?.path === target ? previous.data : null, error: null, pending: true,
      }));
      try {
        const data = await fleetMindRequest<T>(target, { signal: controller.signal });
        if (!controller.signal.aborted) setState({ path: target, data, error: null, pending: false });
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "Unable to reach FleetMind.";
          setState((previous) => ({
            path: target, data: previous?.path === target ? previous.data : null, error: message,
            status: error instanceof FleetMindApiError ? error.status : undefined, pending: false,
          }));
        }
      } finally {
        request = null;
      }
    }

    const initial = window.setTimeout(() => { void load(); }, delay);
    const timer = pollMs ? window.setInterval(() => { void load(); }, pollMs) : undefined;
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
      request?.abort();
    };
  }, [path, pollMs, delay, revision]);

  return state?.path === path ? state : { data: null, error: null, status: undefined, pending: path !== null };
}
