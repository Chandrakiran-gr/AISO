"use server";

import { signIn } from "@/auth";
import { AuthApiError, createCredentialsUser } from "@/lib/auth-api";
import { redirect } from "next/navigation";

function isNextRedirect(e: unknown): boolean {
  if (!(e instanceof Error)) return false;
  const digest = "digest" in e ? e.digest : undefined;
  return (
    e.message === "NEXT_REDIRECT" ||
    (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT"))
  );
}

function authErrorUrl(path: "/login" | "/signup", error: string): string {
  return `${path}?error=${encodeURIComponent(error)}`;
}

function getFormString(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
}

export async function signInWithGoogle(
  callbackUrl: string,
  failurePath: "/login" | "/signup" = "/login"
) {
  try {
    await signIn("google", { redirectTo: callbackUrl });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    redirect(authErrorUrl(failurePath, "OAuthSignin"));
  }
}

export async function signInWithCredentials(
  callbackUrl: string,
  formData: FormData
) {
  const email = getFormString(formData, "email");
  const password = getFormString(formData, "password");

  try {
    await signIn("credentials", { email, password, redirectTo: callbackUrl });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    redirect(authErrorUrl("/login", "invalid"));
  }
}

export async function signUpWithCredentials(
  callbackUrl: string,
  formData: FormData
) {
  const name = getFormString(formData, "name");
  const email = getFormString(formData, "email");
  const password = getFormString(formData, "password");

  try {
    await createCredentialsUser({ name, email, password });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;

    if (e instanceof AuthApiError) {
      if (e.code === "email_exists") {
        redirect(authErrorUrl("/signup", "email_exists"));
      }
      if (e.status >= 500 || e.code === "auth_api_error") {
        redirect(authErrorUrl("/signup", "service_unavailable"));
      }
    }

    redirect(authErrorUrl("/signup", "invalid"));
  }

  try {
    await signIn("credentials", { email, password, redirectTo: callbackUrl });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    redirect(authErrorUrl("/signup", "signin_failed"));
  }
}
