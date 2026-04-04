import { useState, useEffect, useCallback } from 'react';
import { api, type CreditStatus } from '../api/client';

/**
 * Hook to check fal.ai credit status.
 * Polls every 60s and exposes a manual recheck.
 */
export function useCredits() {
  const [credits, setCredits] = useState<CreditStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const recheck = useCallback(async () => {
    try {
      await api.clearCreditCache();
      const result = await api.checkCredits();
      setCredits(result);
    } catch {
      // If endpoint doesn't exist yet, fail silently
      setCredits(null);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    api.checkCredits()
      .then((r) => { if (mounted) setCredits(r); })
      .catch(() => { if (mounted) setCredits(null); })
      .finally(() => { if (mounted) setLoading(false); });

    // Poll every 5 minutes instead of 60s — credit status changes rarely
    // and the server caches for 60s anyway. Previous 60s interval was
    // generating a $0.003 Flux Schnell call each time = $4.32/day waste.
    const interval = setInterval(() => {
      api.checkCredits()
        .then((r) => { if (mounted) setCredits(r); })
        .catch(() => {});
    }, 300_000);

    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const isExhausted = credits?.status === 'exhausted';
  const isNoKey = credits?.status === 'no_key';
  const isActive = credits?.status === 'active';
  const hasIssue = isExhausted || isNoKey || credits?.status === 'invalid_key';

  return { credits, loading, recheck, isExhausted, isNoKey, isActive, hasIssue };
}
