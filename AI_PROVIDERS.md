# AI options in Veloura: what users need and what it costs

Last checked: **2026-10-20**. Veloura never charges for AI: each user pays their AI company directly, or uses a free
option. This file is the single source for the app's Setup/Settings wording, the website and the Gumroad page.
**When anything below changes, update this file first, then every place listed under "Where this info appears".**

| Option | What the user needs | What it costs them | Free? |
|---|---|---|---|
| **ChatGPT** (recommended) | A **paid** ChatGPT plan: **Go, Plus or Pro**. Sign in with "Continue with ChatGPT". | Their ChatGPT subscription (Plus is $20/month). Each beat counts toward their plan's usage limits; no extra charge. | **No.** OpenAI refuses free ChatGPT accounts. Veloura then tells them to use Gemini or Offline. |
| **Claude API** | An Anthropic API key (console.anthropic.com) | Pay per use. Rough cost per beat: Haiku under 1¢ (default), Sonnet about 5¢, Opus about 10–15¢. | No (pay as you go) |
| **Google Gemini** | A Gemini API key (aistudio.google.com/apikey) | Free tier available, with Google's rate limits; paid keys are billed by Google. | **Yes**, with limits. Free tier: Google may use the requests to improve its products; not offered in the EEA, UK or Switzerland (paid key needed there); 18+. |
| **Offline composer** | Nothing | Free | **Yes**, always. Not AI: simple rule-based patterns. |
| Claude (developer) | the developer's own Claude login | the developer's Claude plan | Developer copy only; customers never see it. |

## What we learned (2026-10-19)
- The ChatGPT "use your plan in other apps" program only works for paid plans. On a free account, the browser sign-in
  can show "success" and the app still fails with `invalid_grant`, or OpenAI asks to upgrade. the developer's sign-in
  worked right after upgrading to Plus.
- There is no way for Veloura to let free ChatGPT users in; that is OpenAI's rule. Free users go to Gemini (free
  tier) or Offline.
- Rough Claude per-beat costs assume about 16k input tokens (half cached) and 1–5k output tokens per beat, at
  Anthropic's prices per million tokens: Haiku $0.10 in / $0.50 out, Sonnet $2 / $10, Opus $4 / $20.

## Where this info appears (update all of them)
- App: `app/ui/app.js` (PROVIDER_INFO card text, the ChatGPT sheet, the Gemini note), `veloura/chatgpt.py`
  (PLAN_MESSAGE), `veloura/ai.py` (CLAUDE_MODELS cost labels).
- Testers' / customers' "Read me first.txt" in the release zip.
- Website (tavamadethis.com) and the Gumroad page: a "Which AI should I pick?" section with the table above.

## Re-check before each release
- OpenAI: which ChatGPT plans can sign in to other apps (developers.openai.com/siwc), and the plan prices.
- Anthropic: model prices (anthropic.com/pricing); recompute the per-beat estimates.
- Google: Gemini free-tier limits, regions and terms (ai.google.dev/gemini-api/docs/pricing).
