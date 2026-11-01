"use client";

/**
 * Authentication context.
 *
 * Deliberately small: the session lives in `api.ts` (tokens in memory plus a refresh
 * token in `sessionStorage`), and this provider only mirrors the current user into React
 * state and handles the restore-on-mount.
 *
 * Role helpers are exposed here rather than scattered through components so that "can
 * this person approve a change?" has one answer in the UI — though the server is the
 * authority, and every one of these checks is enforced again there.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, onAuthChange } from "./api";
import type { MembershipRole, User } from "./types";

interface AuthState {
  user: User | null;
  /** True until the initial session restore settles. Gate redirects on this. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void api
      .restoreSession()
      .then((restored) => {
        if (!cancelled) setUser(restored);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The api client announces sign-out when a refresh fails, so an expired session clears
  // the UI rather than leaving a stale user in place.
  useEffect(() => onAuthChange(setUser), []);

  const signIn = useCallback(async (email: string, password: string) => {
    const signedIn = await api.login(email, password);
    setUser(signedIn);
    return signedIn;
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, signIn, signOut, refresh }),
    [user, loading, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return context;
}

// =====================================================================================
// Role helpers
// =====================================================================================

const MEMBERSHIP_RANK: Record<MembershipRole, number> = {
  viewer: 1,
  engineer: 2,
  admin: 3,
};

export function isIometeStaff(user: User | null): boolean {
  return Boolean(user?.is_iomete_staff);
}

export function isPlatformAdmin(user: User | null): boolean {
  return user?.system_role === "platform_admin";
}

export function canApproveKnowledge(user: User | null): boolean {
  if (!user) return false;
  return ["fde", "fde_lead", "platform_admin"].includes(user.system_role);
}

/**
 * Does the user hold at least `minimum` in an organization?
 *
 * Rank-based, so an admin satisfies a check for engineer. IOMETE staff are *not* granted
 * membership roles implicitly — the two role systems are separate, and conflating them in
 * the UI would misrepresent what the server will allow.
 */
export function hasMembershipRole(
  user: User | null,
  minimum: MembershipRole,
  organizationId?: string,
): boolean {
  if (!user) return false;
  const required = MEMBERSHIP_RANK[minimum];
  return user.memberships.some(
    (membership) =>
      (!organizationId || membership.organization_id === organizationId) &&
      MEMBERSHIP_RANK[membership.role] >= required,
  );
}

/**
 * Can this user approve a system-changing playbook step?
 *
 * Mirrors `playbooks.services.execution.can_approve`: IOMETE staff always, or an admin of
 * the organization that owns the execution. Used only to choose which interface to show —
 * the server refuses regardless of what the UI renders.
 */
export function canApproveChange(user: User | null, organizationId?: string): boolean {
  if (!user) return false;
  if (user.is_iomete_staff) return true;
  return hasMembershipRole(user, "admin", organizationId);
}

export function primaryOrganization(user: User | null) {
  if (!user || user.memberships.length === 0) return null;
  return user.memberships.find((membership) => membership.is_default) ?? user.memberships[0]!;
}

/** Where a user should land after signing in, based on which side they are on. */
export function homePathFor(user: User | null): string {
  if (!user) return "/login";
  if (user.system_role === "platform_admin") return "/admin/users";
  if (user.is_iomete_staff) return "/fde/knowledge-review";
  return "/app/support";
}

/**
 * Where to send someone after signing in.
 *
 * A `?next=` path is honoured only when the signed-in user could plausibly be there. A
 * customer who hit a protected `/fde` page should not be bounced back into it, and an
 * engineer who arrived from a customer link should land in their own workspace rather
 * than in the portal — which is what happens if `next` is trusted blindly.
 */
export function postLoginPath(user: User | null, next: string | null): string {
  const home = homePathFor(user);
  // Only same-origin absolute paths. `//evil.com` is protocol-relative, not a local path.
  if (!next || !next.startsWith("/") || next.startsWith("//")) return home;

  const area = next.split("/")[1];
  const staff = Boolean(user?.is_iomete_staff);
  if ((area === "fde" || area === "admin") && !staff) return home;
  if (area === "app" && staff) return home;
  return next;
}
