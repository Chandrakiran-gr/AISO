import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import Credentials from "next-auth/providers/credentials";
import { z } from "zod";
import { upsertOAuthUser, verifyCredentialsUser } from "@/lib/auth-api";

// ── Validation schemas ───────────────────────────────────────────────────────
const loginSchema = z.object({
  email: z.string().email().max(254),
  password: z.string().min(8).max(128),
});

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    // Google OAuth — free, zero cost, highest conversion
    Google({
      clientId:     process.env.AUTH_GOOGLE_ID!,
      clientSecret: process.env.AUTH_GOOGLE_SECRET!,
    }),

    // Email + password fallback
    Credentials({
      name: "credentials",
      credentials: {
        email:    { label: "Email",    type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        // Validate input shape first (prevent injection in auth)
        const parsed = loginSchema.safeParse(credentials);
        if (!parsed.success) return null;

        const { email, password } = parsed.data;
        const user = await verifyCredentialsUser({ email, password });
        return { id: user.id, email: user.email, name: user.name };
      },
    }),
  ],

  // Use JWT sessions (no database needed for Phase 1)
  session: { strategy: "jwt", maxAge: 3600 }, // 1 hour

  pages: {
    signIn:  "/login",
    error:   "/login",
    signOut: "/",
  },

  callbacks: {
    // Attach durable database user id to JWT
    async jwt({ token, user, account }) {
      if (user?.email && account?.provider === "google") {
        try {
          const persisted = await upsertOAuthUser({
            email: user.email,
            name: user.name,
            provider: "google",
          });
          token.id = persisted.id;
          token.email = persisted.email;
          token.name = persisted.name;
        } catch (e) {
          console.error("[AISO Auth] Failed to persist Google user", e);
          throw new Error("Google account setup failed");
        }
      } else if (user) {
        token.id = user.id;
        token.email = user.email;
        token.name = user.name;
      }
      return token;
    },
    // Expose id in session
    async session({ session, token }) {
      if (token.id) session.user.id = token.id as string;
      if (typeof token.email === "string") session.user.email = token.email;
      if (typeof token.name === "string") session.user.name = token.name;
      return session;
    },
  },

  // Security settings
  cookies: {
    sessionToken: {
      options: {
        httpOnly: true,
        secure:   process.env.NODE_ENV === "production",
        sameSite: "lax",
        path:     "/",
      },
    },
  },

  trustHost: true, // Required for local dev
});
