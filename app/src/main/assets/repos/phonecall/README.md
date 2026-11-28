# phonecall

Let your agent make phone calls. A Grok Voice agent places the call through Twilio and sounds like a person. When it needs a decision, it asks your agent mid-call and keeps the line open. When the call ends, you get a summary and the full transcript.

![How an agent makes a phone call](media/how-it-works.png)

## Quick start

You need:

- a Cloudflare account
- an [xAI API key](https://console.x.ai)
- a Twilio account with a voice number (trial accounts can only call verified numbers)
- Node 20 or later

```sh
git clone https://github.com/anomalyco/phonecall && cd phonecall
npm install
npx wrangler deploy   # prints your Worker URL: https://phonecall.<you>.workers.dev
npm run setup         # asks for your keys, connects your number to xAI, stores the secrets
npm link              # puts the phonecall CLI on your PATH
```

Make a test call. A second AI plays the other side, and nobody is dialed:

```sh
phonecall call --simulate "You run the counter at a busy pizza place." \
  --brief "Order a large pepperoni for pickup at 7pm." --watch
```

Then call a real number:

```sh
phonecall call +14155550100 --watch \
  --brief "Book a table for 2 on Friday around 7pm. Anything from 6:30 to 8 is fine."
```

## Use it from an agent

The Worker is also an MCP server at `/mcp`. In OpenCode, add this to `opencode.json`:

```json
{
  "mcp": {
    "phonecall": {
      "type": "remote",
      "url": "https://phonecall.<you>.workers.dev/mcp",
      "oauth": false,
      "timeout": 90000,
      "headers": { "Authorization": "Bearer {file:~/.config/phonecall/token}" }
    }
  }
}
```

Other MCP clients need the same URL and an `Authorization: Bearer <token>` header. The token is in `~/.config/phonecall/token`. `phonecall_watch` can take up to 50 seconds, so allow at least that much time per tool call.

| Tool | What it does |
| --- | --- |
| `phonecall_start` | Starts a call from a number and a brief, and returns a `job_id` |
| `phonecall_watch` | Waits for the next question or the end of the call |
| `phonecall_reply` | Answers a question while the call is live |
| `phonecall_report` | Returns the summary, the questions and the transcript |
| `phonecall_list` | Lists recent calls |
| `phonecall_hangup` | Ends a call now |

An agent calls `phonecall_start`, then calls `phonecall_watch` repeatedly. What it does next depends on the type `phonecall_watch` returns:

- `input_request`: the caller is on the line waiting for an answer. Reply within about a minute.
- `running`: nothing new yet. Watch again.
- `done`: the call is over, and the report is included.

## CLI

| Command | What it does |
| --- | --- |
| `phonecall call <number> --brief "…"` | Starts a call. Add `--watch` to follow it live |
| `phonecall watch <job>` | Prints progress, then exits with one JSON line: a question to answer, or the final report |
| `phonecall reply <job> <question-id> "…"` | Answers a question |
| `phonecall report <job>` | Shows the summary, the questions and the transcript |
| `phonecall transcript <job>` | Shows the transcript as plain text |
| `phonecall list` | Lists recent calls |
| `phonecall hangup <job>` | Ends a call now |

`call` also takes these options:

- `--for` sets who the call is for.
- `--as` sets the caller's name (default Sam).
- `--voice` picks `eve`, `ara`, `rex`, `sal` or `leo`.
- `--max-minutes` caps the call length (default 10).
- `--answer-timeout` sets how many seconds the caller waits for an answer (default 60).

## Writing a brief

The brief is the only thing the caller knows. Include:

- the goal
- the facts it may share
- what it may decide on its own
- what to ask you about first

For example:

```text
Move my dentist cleaning at Bright Smile Dental from Thursday Nov 12 at 2pm
to any weekday morning next week. My date of birth is March 3, 1990, if they
need it. Don't agree to any fee without asking me.
```

Anything outside the brief turns into a question for you. The caller never makes up details. It never pays for or signs up to anything unless the brief allows it.

## How it works

- Twilio dials the number. When someone answers, TwiML `<Dial><Sip>` connects the call to xAI's SIP endpoint. An `X-Job-Id` header tells the Worker which job the call belongs to.
- A Durable Object per call joins the call over xAI's realtime WebSocket (Grok Voice 3.0). It gives the voice agent a prompt (`src/prompt.ts`) and four tools: `send_dtmf`, `request_input`, `check_messages` and `end_call`.
- Questions go to whoever is watching. Answers reach the voice agent as a `check_messages` tool result, which it relays straight away.
- When Twilio reports that the call has ended, Grok 4.7 writes the report from the transcript.
- Simulated calls dial a second xAI SIP number, where another Grok session plays the other side. That number comes from the fictional 555-0100 to 555-0199 range, so it can't be a real line.

## Configuration

`npm run setup` stores everything as Worker secrets. Nothing is kept in the repo.

| Secret | Value |
| --- | --- |
| `XAI_API_KEY` | Your xAI API key |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Your Twilio credentials |
| `TWILIO_PHONE_NUMBER` | The number calls come from |
| `PRINCIPAL_NAME` | Who calls are made for, by default |
| `PHONECALL_TOKEN` | The bearer token for the API, CLI and MCP |
| `SIP_USERNAME`, `SIP_PASSWORD`, `XAI_WEBHOOK_SECRET`, `SIM_NUMBER` | Created by setup for the xAI SIP connection |

You can also set `AGENT_NAME`, `VOICE` and `SUMMARY_MODEL` with `npx wrangler secret put` to change the defaults (`Sam`, `eve`, `grok-4.7`).

Running `npm run setup` again replaces the xAI registration and SIP credentials. It makes a new API token unless `PHONECALL_TOKEN` is set in your environment. Run `npm run setup -- --no-sim` to skip the simulator number.

## Good to know

- A call costs about $0.10 a minute: Grok Voice is $0.08, and Twilio outbound plus SIP is about $0.02 in the US.
- The caller never claims to be human. If someone asks, it says it's an AI assistant.
- Rules on AI calls vary by place. For example, the FCC treats AI voices as artificial voices under the TCPA. Check the rules that apply to you before calling people.
- Setup leaves your Twilio number's incoming-call settings alone. Calls back to that number go wherever they went before.

## License

MIT
