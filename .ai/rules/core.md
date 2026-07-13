# Core rules — billy-ai

Always applicable. Read before writing any code.

1. **This repo is PUBLIC.** Never commit API keys, tokens, customer part
   lists, customer Excel files, parsed output workbooks, or anything
   identifying Central Components' customers or pricing. Secrets live in
   environment variables or gitignored local settings files.
2. **LLM access goes through one provider-agnostic client.** No provider SDK
   calls scattered through the code, no hard-coded model names outside the
   client/config, and never a key in source. Runs use the operator's OpenAI
   key today; end users supply their own key via the app's settings.
3. **Part numbers are sacred.** Anything written to an output workbook is
   character-for-character what the source showed. Normalization (case,
   dashes, whitespace) exists only for matching, never for output.
4. **AI at the edges only.** AI may discover structure (websites) or extract
   pages (PDFs). Volume work — crawling, API calls, Excel writing, filtering —
   is deterministic code. If a change puts an LLM call inside a per-part loop
   on the web pipeline, it's wrong.
5. **Non-technical end users.** No feature may require a terminal, a config
   file edit, or an error message that assumes programming knowledge.
