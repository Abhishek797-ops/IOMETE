"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ArrowRight, LogIn, Users } from "lucide-react";

import { api } from "@/lib/api";
import { postLoginPath, useAuth } from "@/lib/auth";
import { useMutation, useResource } from "@/lib/hooks";
import type { DemoAccount } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Wordmark } from "@/components/layout/Logo";
import {
  Badge,
  Button,
  Card,
  Eyebrow,
  FormError,
  Input,
  SimulatedNotice,
  Skeleton,
} from "@/components/ui";

/**
 * Sign-in.
 *
 * Carries a one-click demo account picker, because a reviewer should be able to see the
 * FDE command center without being handed credentials out of band. The list comes from
 * `/api/v1/auth/demo-accounts/`, which only returns accounts explicitly flagged synthetic
 * and only while demo mode is on — so a real deployment cannot publish a working
 * credential list through this page.
 */
/**
 * `useSearchParams` reads a value that only exists per request, so Next requires it to
 * sit inside a Suspense boundary — otherwise the whole page is forced out of static
 * prerendering. The shell below renders immediately; the form streams in.
 */
export default function LoginPage() {
  return (
    <React.Suspense fallback={<LoginSkeleton />}>
      <LoginForm />
    </React.Suspense>
  );
}

function LoginSkeleton() {
  return (
    <div className="min-h-dvh bg-surface">
      <div className="mx-auto grid min-h-dvh max-w-[86rem] gap-0 px-4 sm:px-6 lg:grid-cols-[1fr_1.1fr] lg:gap-16 lg:px-8">
        <div
          className="flex flex-col justify-center py-12 lg:py-16"
          role="status"
          aria-label="Loading sign-in"
        >
          <div className="mb-10">
            <Wordmark />
          </div>
          <div className="w-full max-w-md space-y-4">
            <Skeleton className="h-9 w-32" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-[4.5rem] w-full" rounded="lg" />
            <Skeleton className="h-[4.5rem] w-full" rounded="lg" />
            <Skeleton className="h-11 w-full" rounded="lg" />
          </div>
        </div>
      </div>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, loading, signIn } = useAuth();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");

  const next = params.get("next");
  const demo = useResource<{ demo_mode: boolean; accounts: DemoAccount[] }>(
    () => api.demoAccounts(),
    [],
  );

  const submit = useMutation(
    async (credentials: { email: string; password: string }) =>
      signIn(credentials.email, credentials.password),
    {
      onSuccess: (signedIn) => {
        router.push(postLoginPath(signedIn, next));
      },
    },
  );

  // Already signed in: go where they belong rather than showing a form they do not need.
  React.useEffect(() => {
    if (!loading && user) {
      router.replace(postLoginPath(user, next));
    }
  }, [loading, user, router, next]);

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void submit.run({ email, password });
  };

  const useAccount = (account: DemoAccount) => {
    setEmail(account.email);
    setPassword(account.password);
    void submit.run({ email: account.email, password: account.password });
  };

  const grouped = React.useMemo(() => {
    const accounts = demo.data?.accounts ?? [];
    return {
      staff: accounts.filter((account) => account.system_role !== "customer"),
      customers: accounts.filter((account) => account.system_role === "customer"),
    };
  }, [demo.data]);

  return (
    <div className="min-h-dvh bg-surface">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <div className="mx-auto grid min-h-dvh max-w-[86rem] gap-0 px-4 sm:px-6 lg:grid-cols-[1fr_1.1fr] lg:gap-16 lg:px-8">
        {/* Sign-in form */}
        <div className="flex flex-col justify-center py-12 lg:py-16">
          <Link href="/" className="mb-10 inline-block w-fit text-ink">
            <Wordmark />
          </Link>

          <main id="main" className="w-full max-w-md">
            <h1 className="text-h1 text-ink">Sign in</h1>
            <p className="mt-2 text-small text-ink-muted">
              Customers reach their support workspace. IOMETE staff reach the FDE command
              center.
            </p>

            <form onSubmit={onSubmit} className="mt-8 space-y-4" noValidate>
              <Input
                label="Email address"
                type="email"
                name="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                error={submit.fieldErrors.email}
                placeholder="you@yourcompany.example"
              />
              <Input
                label="Password"
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                error={submit.fieldErrors.password}
              />

              <FormError error={submit.error} />

              <Button
                type="submit"
                variant="primary"
                size="lg"
                fullWidth
                loading={submit.pending}
                icon={<LogIn />}
              >
                Sign in
              </Button>
            </form>

            <p className="mt-6 text-small text-ink-muted">
              Not a customer yet?{" "}
              <Link
                href="/explore"
                className="font-medium text-accent-700 underline underline-offset-2 dark:text-accent-300"
              >
                Explore what IOMETE does
              </Link>{" "}
              or{" "}
              <Link
                href="/request-demo"
                className="font-medium text-accent-700 underline underline-offset-2 dark:text-accent-300"
              >
                request a demo
              </Link>
              .
            </p>
          </main>
        </div>

        {/* Demo accounts */}
        <div className="flex flex-col justify-center border-t border-border py-12 lg:border-l lg:border-t-0 lg:py-16 lg:pl-16">
          <div className="w-full max-w-lg">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-simulated-soft text-simulated [&>svg]:size-4"
              >
                <Users />
              </span>
              <Eyebrow as="h2">Demonstration accounts</Eyebrow>
            </div>

            {demo.loading && (
              <div className="mt-6 space-y-2.5" role="status" aria-label="Loading demo accounts">
                {[0, 1, 2, 3].map((index) => (
                  <Skeleton key={index} className="h-[4.5rem] w-full" rounded="lg" />
                ))}
              </div>
            )}

            {!demo.loading && !demo.data?.demo_mode && (
              <p className="mt-5 text-small text-ink-muted">
                This deployment is not in demonstration mode, so no demo accounts are
                published. Sign in with your own credentials.
              </p>
            )}

            {!demo.loading && demo.data?.demo_mode && (demo.data.accounts.length === 0) && (
              <p className="mt-5 text-small text-ink-muted">
                No demonstration accounts have been seeded yet. Run{" "}
                <code className="rounded border border-border bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.8rem]">
                  python manage.py seed_demo
                </code>{" "}
                in the backend to create them.
              </p>
            )}

            {!demo.loading && (demo.data?.accounts.length ?? 0) > 0 && (
              <>
                <p className="mt-3 text-small text-ink-muted">
                  Pick a role to sign in immediately. Each one sees a genuinely different
                  product — a customer engineer cannot approve a cluster change, and only an
                  FDE can approve knowledge.
                </p>

                <SimulatedNotice compact className="mt-4">
                  These are synthetic accounts in a demonstration deployment. They are
                  published only because demo mode is enabled and each is flagged synthetic.
                </SimulatedNotice>

                {grouped.staff.length > 0 && (
                  <section className="mt-6">
                    <h3 className="text-micro uppercase text-ink-subtle">IOMETE staff</h3>
                    <ul className="mt-2.5 space-y-2.5">
                      {grouped.staff.map((account) => (
                        <li key={account.email}>
                          <AccountButton
                            account={account}
                            pending={submit.pending && email === account.email}
                            onSelect={useAccount}
                          />
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {grouped.customers.length > 0 && (
                  <section className="mt-6">
                    <h3 className="text-micro uppercase text-ink-subtle">Customers</h3>
                    <ul className="mt-2.5 space-y-2.5">
                      {grouped.customers.map((account) => (
                        <li key={account.email}>
                          <AccountButton
                            account={account}
                            pending={submit.pending && email === account.email}
                            onSelect={useAccount}
                          />
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountButton({
  account,
  pending,
  onSelect,
}: {
  account: DemoAccount;
  pending: boolean;
  onSelect: (account: DemoAccount) => void;
}) {
  const roleTone =
    account.system_role === "platform_admin"
      ? "critical"
      : account.system_role === "fde_lead"
        ? "accent"
        : account.system_role === "fde"
          ? "info"
          : "neutral";

  return (
    <button
      type="button"
      onClick={() => onSelect(account)}
      disabled={pending}
      className={cn(
        "group w-full rounded-lg border border-border bg-surface-raised p-3.5 text-left",
        "transition-[border-color,background-color,transform] duration-150",
        "hover:-translate-y-0.5 hover:border-accent-300 hover:bg-accent-50/40",
        "disabled:opacity-60",
      )}
    >
      <Card tone="flat" padded={false} className="border-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-small font-medium text-ink">
              {account.full_name}
              <Badge tone={roleTone} size="sm">
                {account.system_role.replace(/_/g, " ")}
              </Badge>
            </p>
            <p className="mt-0.5 truncate font-mono text-[0.75rem] text-ink-subtle">
              {account.email}
            </p>
            <p className="mt-1.5 text-small text-ink-muted">{account.description}</p>
            {account.organization && (
              <p className="mt-1 text-[11px] text-ink-subtle">{account.organization}</p>
            )}
          </div>
          <ArrowRight
            aria-hidden="true"
            className="mt-1 size-4 shrink-0 text-ink-subtle transition-transform duration-150 group-hover:translate-x-0.5"
          />
        </div>
      </Card>
    </button>
  );
}
