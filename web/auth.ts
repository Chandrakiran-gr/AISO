import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import Credentials from "next-auth/providers/credentials";
import { z } from "zod";

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

        // TODO Phase 3: query SQLite/PostgreSQL with bcrypt compare
        // For now — placeholder that always fails (forces Google OAuth in dev)
        // Replace with:
        //   const user = await db.getUserByEmail(email);
        //   if (!user) return null;
        //   const valid = await bcrypt.compare(password, user.passwordHash);
        //   if (!valid) return null;
        //   return { id: user.id, email: user.email, name: user.name };
        void email; void password;
        return null;
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
    // Attach user id to JWT
    async jwt({ token, user }) {
      if (user) token.id = user.id;
      return token;
    },
    // Expose id in session
    async session({ session, token }) {
      if (token.id) session.user.id = token.id as string;
      return session;
    },
  },

  // Security settings
  cookies: {
    sessionToken: {
      options: {
        httpOnly: true,
        secure:   process.env.NODE_ENV === "production",
        sameSite: "strict",
        path:     "/",
      },
    },
  },

  trustHost: true, // Required for local dev
});
