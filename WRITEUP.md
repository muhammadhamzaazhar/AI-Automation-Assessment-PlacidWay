# Write-up

## Known limitations

- The bot only knows the 7 pages. Anything else gets "not on these pages" and a free-quote offer.
- The code checks numbers, not wording. An invented non-numeric claim is prevented only by the prompt.
- Extraction depends on PlacidWay's current page layout; a redesign would need selector updates.
- Answers take about 4–6 seconds (two LLM calls, no streaming).
- Leads and logs are stored in SQLite on the server and reset if the container restarts.

## With another week

- Stream answers so text appears sooner.
- Check every sentence of an answer against its sources, not just the numbers.
- Store prices as structured data during ingestion.
- Build a larger test set from real unanswered questions and run it on every change.
- Move leads and logs to a proper database and send new leads to a CRM or email.
