"use server";

import { signIn } from "@/auth";
import { redirect } from "next/navigation";

export async function signInWithGoogle(callbackUrl: string) {
  await signIn("google", { redirectTo: callbackUrl });
}

export async function signInWithCredentials(
  callbackUrl: string,
  formData: FormData
) {
  const email    = formData.get("email")    as string;
  const password = formData.get("password") as string;

  try {
    await signIn("credentials", { email, password, redirectTo: callbackUrl });
  } catch (e: unknown) {
    // NextAuth throws a redirect — re-throw it; other errors go to /login?error=...
    const isRedirect =
      e instanceof Error && e.message === "NEXT_REDIRECT";
    if (isRedirect) throw e;
    redirect(`/login?error=invalid`);
  }
}
