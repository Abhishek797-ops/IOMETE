"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ArrowRight, ExternalLink, Menu, X } from "lucide-react";

import { useAuth, homePathFor } from "@/lib/auth";
import { useEscapeKey, useResetOnChange, useScrollLock } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { Button, IconButton } from "@/components/ui";

import { DemoBanner } from "./DemoBanner";
import { Wordmark } from "./Logo";

const NAV = [
  { href: "/explore", label: "Explore IOMETE", description: "What a lakehouse is, in plain language" },
  { href: "/architecture", label: "Architecture", description: "How it fits your infrastructure" },
  { href: "/fit-finder", label: "Fit Finder", description: "An indicative suitability assessment" },
  {
    href: "/lakehouse-playground",
    label: "Playground",
    description: "Run real SQL against a demo lakehouse",
  },
  { href: "/call-prep", label: "Call prep", description: "A sourced brief before your call" },
] as const;

/**
 * The public shell: warm surface, sticky header, honest footer.
 *
 * The header collapses to a sheet below `lg` rather than cramming five items into a
 * narrow bar. The footer carries the factual-accuracy statement, because a product that
 * makes claims about someone else's software should say where those claims came from in a
 * place people can find.
 */
export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();
  // Keyed on the pathname so navigating closes the sheet. Adjusting state during render
  // against a stored key is React's own recommendation for this, and it avoids the
  // cascading render an effect would cause on every navigation.
  const [menuOpen, setMenuOpen] = useResetOnChange(pathname, false);

  useEscapeKey(() => setMenuOpen(false), menuOpen);
  useScrollLock(menuOpen);

  return (
    <div className="flex min-h-dvh flex-col bg-surface">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <DemoBanner />

      <header className="sticky top-0 z-40 border-b border-border bg-surface/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[86rem] items-center gap-6 px-4 sm:px-6 lg:px-8">
          <Link
            href="/"
            className="shrink-0 rounded text-ink transition-opacity hover:opacity-80"
            aria-label="IOMETE COMPASS — home"
          >
            <Wordmark compact />
          </Link>

          <nav aria-label="Main" className="hidden flex-1 items-center gap-1 lg:flex">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "rounded-md px-3 py-2 text-small font-medium transition-colors",
                    active
                      ? "bg-surface-inset text-ink"
                      : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2 lg:ml-0">
            {user ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  window.location.href = homePathFor(user);
                }}
                className="hidden sm:inline-flex"
              >
                {user.is_iomete_staff ? "FDE command center" : "Customer portal"}
              </Button>
            ) : (
              <Link
                href="/login"
                className="hidden rounded-md px-3 py-2 text-small font-medium text-ink-muted transition-colors hover:text-ink sm:block"
              >
                Sign in
              </Link>
            )}
            <Link href="/request-demo" className="hidden sm:block">
              <Button variant="primary" size="sm" iconRight={<ArrowRight />}>
                Request a demo
              </Button>
            </Link>
            <IconButton
              label={menuOpen ? "Close menu" : "Open menu"}
              onClick={() => setMenuOpen((value) => !value)}
              className="lg:hidden"
              aria-expanded={menuOpen}
              aria-controls="public-mobile-nav"
            >
              {menuOpen ? <X /> : <Menu />}
            </IconButton>
          </div>
        </div>

        {menuOpen && (
          <div
            id="public-mobile-nav"
            className="border-t border-border bg-surface-raised lg:hidden"
          >
            <nav aria-label="Main" className="mx-auto max-w-[86rem] px-4 py-3 sm:px-6">
              <ul className="space-y-1">
                {NAV.map((item) => {
                  const active = pathname === item.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "block rounded-md px-3 py-2.5",
                          active ? "bg-surface-inset" : "hover:bg-surface-sunken",
                        )}
                      >
                        <span className="block text-small font-medium text-ink">
                          {item.label}
                        </span>
                        <span className="mt-0.5 block text-small text-ink-subtle">
                          {item.description}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
                <Link href="/request-demo">
                  <Button variant="primary" fullWidth iconRight={<ArrowRight />}>
                    Request a demo
                  </Button>
                </Link>
                <Link href={user ? homePathFor(user) : "/login"}>
                  <Button variant="secondary" fullWidth>
                    {user ? "Go to your workspace" : "Sign in"}
                  </Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      <main id="main" className="flex-1">
        {children}
      </main>

      <PublicFooter />
    </div>
  );
}

function PublicFooter() {
  return (
    <footer className="mt-20 border-t border-border bg-surface-sunken">
      <div className="mx-auto max-w-[86rem] px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="max-w-sm">
            <Wordmark />
            <p className="mt-4 text-small text-ink-muted">
              An enablement and support-intelligence tool for IOMETE — a sovereign data
              lakehouse platform built on Apache Spark, Apache Iceberg and Kubernetes.
            </p>
          </div>

          <FooterColumn
            title="Understand"
            links={[
              { href: "/explore", label: "What IOMETE is" },
              { href: "/explore#personas", label: "Explained for your role" },
              { href: "/architecture", label: "Architecture playground" },
            ]}
          />
          <FooterColumn
            title="Evaluate"
            links={[
              { href: "/fit-finder", label: "Fit Finder" },
              { href: "/call-prep", label: "Call prep" },
              { href: "/lakehouse-playground", label: "Lakehouse playground" },
              { href: "/request-demo", label: "Request a demo" },
            ]}
          />
          <FooterColumn
            title="Official IOMETE"
            links={[
              { href: "https://iomete.com/", label: "iomete.com", external: true },
              {
                href: "https://iomete.com/resources",
                label: "Documentation",
                external: true,
              },
              {
                href: "https://iomete.com/resources/getting-started/architecture",
                label: "Architecture docs",
                external: true,
              },
            ]}
          />
        </div>

        {/*
          The accuracy statement. This belongs in the footer of every public page: COMPASS
          makes claims about someone else's product, and a reader is entitled to know
          exactly how those claims are sourced and what COMPASS will not assert.
        */}
        <div className="mt-10 border-t border-border pt-6">
          <p className="measure text-small text-ink-subtle">
            IOMETE COMPASS is an independent enablement tool. Every product statement here
            is transcribed from official IOMETE documentation and carries a source
            reference; anything that could not be verified is labelled rather than
            asserted. COMPASS does not state pricing, named customers, benchmarks, service
            levels, or cost savings for any specific organisation. Support tickets, issue
            clusters and resolution playbooks in this deployment are synthetic engineering
            scenarios created for demonstration — they are not IOMETE incident records.
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({
  title,
  links,
}: {
  title: string;
  links: { href: string; label: string; external?: boolean }[];
}) {
  return (
    <div>
      <h2 className="text-micro uppercase text-ink-subtle">{title}</h2>
      <ul className="mt-3 space-y-2">
        {links.map((link) => (
          <li key={link.href + link.label}>
            {link.external ? (
              <a
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-small text-ink-muted transition-colors hover:text-ink"
              >
                {link.label}
                <ExternalLink aria-hidden="true" className="size-3" />
              </a>
            ) : (
              <Link
                href={link.href}
                className="text-small text-ink-muted transition-colors hover:text-ink"
              >
                {link.label}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A centred content column, for the public pages' prose sections. */
export function PublicSection({
  children,
  className,
  width = "default",
  id,
}: {
  children: React.ReactNode;
  className?: string;
  width?: "default" | "wide" | "narrow";
  id?: string;
}) {
  return (
    <section
      id={id}
      className={cn(
        "mx-auto px-4 sm:px-6 lg:px-8",
        width === "default" && "max-w-[72rem]",
        width === "wide" && "max-w-[86rem]",
        width === "narrow" && "max-w-[52rem]",
        className,
      )}
    >
      {children}
    </section>
  );
}
