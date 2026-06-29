"use server";

import { signIn } from "@/auth";
import {
  AuthApiError,
  createCredentialsUser,
  verifyCredentialsUser,
  verifyOtp,
  resendOtp,
  forgotPassword,
  resetPassword,
} from "@/lib/auth-api";
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
    // signIn failed — distinguish an unverified email from bad credentials so we
    // can route the user to verification rather than showing a generic error.
    let unverified = false;
    try {
      await verifyCredentialsUser({ email, password });
    } catch (inner: unknown) {
      unverified =
        inner instanceof AuthApiError && inner.message === "email_not_verified";
    }
    if (unverified) {
      redirect(`/verify?email=${encodeURIComponent(email)}`);
    }
    redirect(authErrorUrl("/login", "invalid"));
  }
}

export async function signUpWithCredentials(
  _callbackUrl: string,
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

  // No account exists yet — a verification code was emailed. Send the user to the
  // OTP step; the account is created only once the code is verified.
  redirect(`/verify?email=${encodeURIComponent(email)}`);
}

export async function verifyOtpAction(formData: FormData) {
  const email = getFormString(formData, "email");
  const code = getFormString(formData, "code");

  let signinToken: string | undefined;
  try {
    const result = await verifyOtp({ email, code });
    signinToken = result.signin_token ?? undefined;
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    const reason = e instanceof AuthApiError ? e.message : "invalid_code";
    redirect(`/verify?email=${encodeURIComponent(email)}&error=${encodeURIComponent(reason)}`);
  }

  // Verified — sign in with the one-time grant and go straight to onboarding.
  if (signinToken) {
    try {
      await signIn("credentials", {
        email,
        signinToken,
        redirectTo: "/onboarding",
      });
    } catch (e: unknown) {
      if (isNextRedirect(e)) throw e; // success: NextAuth redirected to /onboarding
      // Grant sign-in failed unexpectedly — fall through to manual login below.
    }
  }

  // Fallback (no grant returned, or auto sign-in failed): verified, log in manually.
  redirect("/login?verified=1");
}

export async function resendOtpAction(formData: FormData) {
  const email = getFormString(formData, "email");

  try {
    await resendOtp({ email });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    const reason = e instanceof AuthApiError ? e.message : "resend_failed";
    redirect(`/verify?email=${encodeURIComponent(email)}&error=${encodeURIComponent(reason)}`);
  }

  redirect(`/verify?email=${encodeURIComponent(email)}&resent=1`);
}

export async function forgotPasswordAction(formData: FormData) {
  const email = getFormString(formData, "email");

  try {
    await forgotPassword({ email });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    // Never reveal failures on the reset path (no account enumeration).
  }

  // Always the same confirmation — a reset link is on its way if the account exists.
  redirect("/forgot-password?sent=1");
}

export async function resetPasswordAction(formData: FormData) {
  const token = getFormString(formData, "token");
  const newPassword = getFormString(formData, "new_password");

  try {
    await resetPassword({ token, new_password: newPassword });
  } catch (e: unknown) {
    if (isNextRedirect(e)) throw e;
    const reason = e instanceof AuthApiError ? e.message : "invalid_token";
    // Keep the token in the URL so a recoverable error (weak password) can be retried.
    redirect(`/reset-password?token=${encodeURIComponent(token)}&error=${encodeURIComponent(reason)}`);
  }

  redirect("/login?reset=1");
}
