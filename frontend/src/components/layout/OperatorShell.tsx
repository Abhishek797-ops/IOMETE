"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  Building2,
  ClipboardCheck,
  Database,
  ExternalLink,
  LifeBuoy,
  LogOut,
  Menu,
  Plug,
  ScrollText,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { useEscapeKey, useResetOnChange, useScrollLock } from "@/lib/hooks";
import { cn, initials } from "@/lib/utils";

import { Avatar, Badge, Button, IconButton, Spinner } from "@/components/ui";

import { DemoBanner } from "./DemoBanner";
import { Wordmark } from "./Logo";

type Area = "portal" | "fde" | "admin";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAVIGATION: Record<Area, NavGroup[]> = {
  // Only routes that exist. A sidebar link to an unbuilt page is a button that does
  // nothing, which is worse than an absent feature — it reads as broken rather than
  // out of scope.
  portal: [
    {
      title: "Support",
      items: [{ href: "/app/support", label: "Get help", icon: <LifeBuoy /> }],
    },
  ],
  fde: [
    {
      title: "Knowledge",
      items: [
        { href: "/fde/knowledge-review", label: "Review queue", icon: <ClipboardCheck /> },
      ],
    },
  ],
  admin: [
    {
      title: "Tenancy",
      items: [
        { href: "/admin/organizations", label: "Organizations", icon: <Building2 /> },
        { href: "/admin/users", label: "Users and roles", icon: <Users /> },
      ],
    },
    {
      title: "Platform",
      items: [
        { href: "/admin/knowledge", label: "Product knowledge", icon: <Database /> },
        { href: "/admin/integrations", label: "Integrations", icon: <Plug /> },
        { href: "/admin/audit", label: "Audit history", icon: <ScrollText /> },
      ],
    },
  ],
};

const AREA_LABEL: Record<Area, string> = {
  portal: "Customer portal",
  fde: "FDE command center",
  admin: "Administration",
};

/**
 * The operator shell: graphite chrome, persistent sidebar, area switcher.
 *
 * Dark by design. Someone working in the FDE command center is reading dense technical
 * detail for an hour at a time, and the change of ground also marks the boundary between
 * the marketing surface and the working surface without needing to say so.
 *
 * Access is gated here *and* on the server. This redirect is a courtesy so a customer
 * does not stare at a wall of 403s; the API refuses regardless of what the UI renders.
 */
export function OperatorShell({
  area,
  children,
}: {
  area: Area;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, signOut } = useAuth();
  // Keyed on the pathname so navigating closes the drawer, without an effect.
  const [sidebarOpen, setSidebarOpen] = useResetOnChange(pathname, false);

  useEscapeKey(() => setSidebarOpen(false), sidebarOpen);
  useScrollLock(sidebarOpen);

  React.useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    if ((area === "fde" || area === "admin") && !user.is_iomete_staff) {
      router.replace("/app/dashboard");
      return;
    }
    if (area === "admin" && user.system_role !== "platform_admin") {
      router.replace("/fde/dashboard");
    }
  }, [area, loading, user, router, pathname]);

  if (loading || !user) {
    return (
      <div className="grid min-h-dvh place-items-center bg-graphite-950">
        <div className="flex items-center gap-3 text-ink-inverse-muted">
          <Spinner className="size-5" />
          <span className="text-small">Restoring your session…</span>
        </div>
      </div>
    );
  }

  const groups = NAVIGATION[area];
  const availableAreas: Area[] = user.is_iomete_staff
    ? user.system_role === "platform_admin"
      ? ["fde", "admin", "portal"]
      : ["fde", "portal"]
    : ["portal"];

  return (
    <div className="min-h-dvh bg-graphite-950 text-ink-inverse">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Mobile top bar */}
      <div className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-graphite-800 bg-graphite-900 px-4 lg:hidden">
        <IconButton
          label={sidebarOpen ? "Close navigation" : "Open navigation"}
          onClick={() => setSidebarOpen((value) => !value)}
          aria-expanded={sidebarOpen}
          aria-controls="operator-sidebar"
          className="text-ink-inverse-muted hover:bg-graphite-800 hover:text-ink-inverse"
        >
          {sidebarOpen ? <X /> : <Menu />}
        </IconButton>
        <Link href="/" className="min-w-0 text-ink-inverse" aria-label="IOMETE COMPASS — home">
          <Wordmark compact />
        </Link>
        <div className="ml-auto">
          <Avatar initials={user.avatar_initials || initials(user.full_name)} name={user.full_name} />
        </div>
      </div>

      <div className="lg:flex">
        {/* Sidebar */}
        <div
          id="operator-sidebar"
          className={cn(
            "z-40 w-[17rem] shrink-0 border-r border-graphite-800 bg-graphite-900",
            "lg:sticky lg:top-0 lg:block lg:h-dvh",
            sidebarOpen
              ? "fixed inset-y-0 left-0 block overflow-y-auto"
              : "hidden",
          )}
        >
          <div className="flex h-full flex-col">
            <div className="hidden border-b border-graphite-800 px-5 py-4 lg:block">
              <Link
                href="/"
                className="text-ink-inverse transition-opacity hover:opacity-80"
                aria-label="IOMETE COMPASS — home"
              >
                <Wordmark />
              </Link>
            </div>

            {availableAreas.length > 1 && (
              <div className="border-b border-graphite-800 px-3 py-3">
                <p className="px-2 pb-2 text-micro uppercase text-ink-inverse-subtle">
                  Workspace
                </p>
                <div
                  role="tablist"
                  aria-label="Workspace"
                  className="flex rounded-md bg-graphite-850 p-1"
                >
                  {availableAreas.map((candidate) => (
                    <Link
                      key={candidate}
                      href={
                        candidate === "portal"
                          ? "/app/dashboard"
                          : candidate === "fde"
                            ? "/fde/dashboard"
                            : "/admin/users"
                      }
                      role="tab"
                      aria-selected={candidate === area}
                      className={cn(
                        "flex-1 rounded px-2 py-1.5 text-center text-[11px] font-medium transition-colors",
                        candidate === area
                          ? "bg-graphite-700 text-ink-inverse"
                          : "text-ink-inverse-subtle hover:text-ink-inverse-muted",
                      )}
                    >
                      {candidate === "portal" ? "Customer" : candidate === "fde" ? "FDE" : "Admin"}
                    </Link>
                  ))}
                </div>
              </div>
            )}

            <nav aria-label={AREA_LABEL[area]} className="flex-1 overflow-y-auto px-3 py-4">
              {groups.map((group) => (
                <div key={group.title} className="mb-5 last:mb-0">
                  <h2 className="px-2 pb-2 text-micro uppercase text-ink-inverse-subtle">
                    {group.title}
                  </h2>
                  <ul className="space-y-0.5">
                    {group.items.map((item) => {
                      const active =
                        pathname === item.href || pathname.startsWith(`${item.href}/`);
                      return (
                        <li key={item.href}>
                          <Link
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-small transition-colors",
                              active
                                ? "bg-graphite-800 font-medium text-ink-inverse"
                                : "text-ink-inverse-muted hover:bg-graphite-850 hover:text-ink-inverse",
                            )}
                          >
                            <span
                              aria-hidden="true"
                              className={cn(
                                "shrink-0 [&>svg]:size-4",
                                active ? "text-accent-400" : "text-ink-inverse-subtle",
                              )}
                            >
                              {item.icon}
                            </span>
                            {item.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </nav>

            <div className="border-t border-graphite-800 p-3">
              <div className="flex items-center gap-2.5 rounded-md px-2 py-2">
                <Avatar
                  initials={user.avatar_initials || initials(user.full_name)}
                  name={user.full_name}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-small font-medium text-ink-inverse">
                    {user.full_name}
                  </p>
                  <p className="truncate text-[11px] text-ink-inverse-subtle">
                    {user.email}
                  </p>
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 px-2 pb-2">
                <RoleBadge role={user.system_role} />
                {user.memberships[0] && (
                  <Badge tone="neutral" size="sm" className="border-graphite-700 bg-graphite-850 text-ink-inverse-muted">
                    {user.memberships[0].organization_name}
                  </Badge>
                )}
              </div>
              <div className="flex gap-1.5">
                <Link href="/" className="flex-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    fullWidth
                    icon={<ExternalLink />}
                    className="justify-start text-ink-inverse-muted hover:bg-graphite-850 hover:text-ink-inverse"
                  >
                    Public site
                  </Button>
                </Link>
                <IconButton
                  label="Sign out"
                  size="sm"
                  onClick={() => {
                    void signOut().then(() => router.push("/login"));
                  }}
                  className="text-ink-inverse-muted hover:bg-graphite-850 hover:text-ink-inverse"
                >
                  <LogOut />
                </IconButton>
              </div>
            </div>
          </div>
        </div>

        {sidebarOpen && (
          <div
            aria-hidden="true"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-30 bg-graphite-950/60 lg:hidden"
          />
        )}

        {/* Content. Light surface inside the dark chrome: dense tables and long prose are
            still easier to read on a light ground, and the contrast frames the work. */}
        <div className="min-w-0 flex-1 bg-surface">
          <DemoBanner />
          <main id="main" className="mx-auto max-w-[86rem] px-4 py-7 sm:px-6 lg:px-8 lg:py-9">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const presentation: Record<string, { label: string; icon?: React.ReactNode }> = {
    platform_admin: { label: "Platform admin", icon: <ShieldCheck /> },
    fde_lead: { label: "FDE lead", icon: <ShieldCheck /> },
    fde: { label: "FDE" },
    customer: { label: "Customer" },
  };
  const entry = presentation[role] ?? { label: role };
  return (
    <Badge
      tone="accent"
      size="sm"
      icon={entry.icon}
      className="border-accent-700/40 bg-accent-900/40 text-accent-200"
    >
      {entry.label}
    </Badge>
  );
}

/**
 * A breadcrumb trail for detail pages.
 *
 * Operator detail pages are reachable from several places (inbox, cluster, search), so a
 * trail that names where you are is more useful than a back button that depends on how
 * you arrived.
 */
export function Breadcrumbs({
  items,
  className,
}: {
  items: { href?: string; label: string }[];
  className?: string;
}) {
  return (
    <nav aria-label="Breadcrumb" className={cn("mb-4", className)}>
      <ol className="flex flex-wrap items-center gap-1.5 text-small text-ink-subtle">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-1.5">
              {item.href && !last ? (
                <Link href={item.href} className="transition-colors hover:text-ink">
                  {item.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "text-ink-muted" : undefined}>
                  {item.label}
                </span>
              )}
              {!last && (
                <span aria-hidden="true" className="text-border-strong">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

