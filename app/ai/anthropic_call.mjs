// Veloura AI helper: one Claude request via Anthropic's official TypeScript SDK.
// Input (stdin JSON): {model, system, user, schema}. API key: ANTHROPIC_API_KEY env (set by the Python service from
// the macOS Keychain). Output (stdout, one JSON line): {ok: true, data} or {ok: false, error}.
import Anthropic from "@anthropic-ai/sdk";

const read = async () => {
  let s = "";
  for await (const chunk of process.stdin) s += chunk;
  return JSON.parse(s);
};

const out = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

const main = async () => {
  const req = await read();
  const client = new Anthropic({ timeout: 170_000, maxRetries: 2 });
  const params = {
    model: req.model,
    max_tokens: 16000,
    // The system prompt is the same on every request, so cache it: repeat requests read it at a fraction of the
    // input price. The per-request project context and the user's words come after it, in the user message.
    system: [{ type: "text", text: req.system, cache_control: { type: "ephemeral" } }],
    messages: [{ role: "user", content: req.user }],
    output_config: { effort: "medium", format: { type: "json_schema", schema: req.schema } },
  };
  // Refusal fallback (server-side): re-runs a declined request on Anthropic's recommended fallback model.
  // Haiku has no server-side fallback, so it is only requested for the larger models.
  if (!/haiku/i.test(String(req.model))) {
    params.betas = ["server-side-fallback-2026-07-01"];
    params.fallbacks = "default";
  }
  let response;
  try {
    response = await client.beta.messages.create(params);
  } catch (err) {
    if (err instanceof Anthropic.BadRequestError && /fallback/i.test(String(err.message))) {
      // Fallbacks not enabled for this account/model: retry once without them.
      delete params.betas;
      delete params.fallbacks;
      response = await client.messages.create(params);
    } else {
      throw err;
    }
  }
  if (response.stop_reason === "refusal") {
    return out({ ok: false, error: "The model declined this request." });
  }
  if (response.stop_reason === "max_tokens") {
    return out({ ok: false, error: "The response was cut off (too long). Try asking for fewer bars or parts." });
  }
  const text = response.content.filter((b) => b.type === "text").map((b) => b.text).join("");
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return out({ ok: false, error: "The model's reply was not valid JSON." });
  }
  out({ ok: true, data, usage: response.usage, model: response.model });
};

main().catch((err) => {
  let msg = String(err && err.message ? err.message : err);
  if (err instanceof Anthropic.AuthenticationError) msg = "The Anthropic API key was rejected. Check it in Settings.";
  else if (err instanceof Anthropic.RateLimitError) msg = "Rate limited by the Anthropic API. Try again in a minute.";
  else if (err instanceof Anthropic.APIConnectionError) msg = "Could not reach the Anthropic API. Check your internet connection.";
  out({ ok: false, error: msg });
});
