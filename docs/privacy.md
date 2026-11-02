# Privacy

FPL Copilot is a small, independent fantasy-football assistant. This page says, in plain words, what we keep about you,
where it goes, and how to have it deleted.

## What we store

- **Your account.** Your name, your email address, how you sign in (Google or email), when you joined and when you last
  used the app. Sign-in itself is handled by Clerk; we never see or store a password.
- **Your messages and the answers.** Each conversation is kept as a thread on our server, so it can continue where you
  left off, together with the tool results the assistant used to answer.
- **Your squad.** The FPL squad versions you save here, and the change previews you are shown before anything is saved.
- **Usage.** For every answer: how many model calls it took, the tokens used and what it cost. We use this to keep each
  account within its daily limit and the service affordable. We also keep the results of the automatic checks run on
  each answer.

## Where it goes

- **Our server.** Everything above is stored in a database on our own server. The database is not open to the internet.
- **Anthropic.** To write each answer, your message and the recent conversation are sent to Anthropic (the company behind
  the Claude models), which processes them to produce the reply.
- **Voyage AI.** When the assistant searches football news, the search words it chose (not your whole message) are sent
  to Voyage AI to find the matching articles.
- **Langfuse (US).** A record of each answer is sent to Langfuse, a monitoring service in the United States, so we can find
  and fix mistakes. It holds your message and the answer, with email addresses replaced by [email] and phone numbers by
  [phone], and it knows you only by an account number, not by your name or email. Langfuse keeps these records for 30 days.
- **Clerk.** Clerk keeps the account you sign in with (your name and email, and your Google account link if you use
  Google sign-in).

We do not sell your data, show advertising, or share it with anyone else.

## How long

Your account, conversations, squads and usage records stay until you ask us to delete them. Langfuse records are removed
after 30 days.

## Deleting your data

Ask through the contact link in the app, from the email address you sign in with, and say you want your data deleted. We
will delete your account, conversations, squads and usage records from our server and remove your Clerk account within
30 days, and confirm when it is done.
