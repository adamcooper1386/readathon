# Readathon Reading Log: Requirements for Claude Code

## Goal

Build a small SMS application that tracks a child's summer reading. A parent or
caregiver texts a dedicated phone number with whatever they read, an AI model
parses the message into structured data, and each reading session is stored in a
SQLite database. At the end of the summer, the user can export a single clean
spreadsheet showing what the child read, on what date, for how long, and with whom.
The system should replace a manual process where one parent received texts and
compiled the times by hand.

## Context and constraints

- The hosting target is a cheap always-on server, for example a small VPS or Fly.io.
- The database must be true SQLite stored on a persistent path that survives restarts.
- The application must record who read with the child on every session.
- The texters are a small fixed group, for example a parent and a caregiver, each with a known phone number.
- The texters should not have to change how they write. The app must tolerate casual, free-form messages.
- The build should be simple to deploy and inexpensive to run.

## Users

- The owner is a parent who sets up the app, holds the export link, and reviews the data.
- The loggers are the adults who read with the child, including the parent and one or more caregivers. They only ever send text messages.

## Primary user flow

1. A logger sends a text to the dedicated number, for example "25 min of Dog Man with Grandma today".
2. The app receives the message through a Twilio webhook.
3. The app sends the message to an AI model and receives structured session data.
4. The app stores each session in SQLite.
5. The app replies with a short confirmation that includes the running summer total.
6. At any time, the owner views a dashboard or downloads a CSV of all sessions.

## Functional requirements

### 1. SMS intake

- Provide an HTTP POST endpoint that receives Twilio inbound message webhooks.
- Read the message body and the sender's phone number from the Twilio request.
- Reply to the sender using a Twilio messaging response so the logger gets a confirmation text.
- Support optional Twilio request signature validation, controlled by configuration, so that in production only signed requests from Twilio are accepted.

### 2. Message parsing

- Send the message body to an AI model and require a strict JSON response.
- The parser must return zero or more sessions from a single message, because one text may describe several reading sessions.
- For each session, extract the title of the book or material, the date, the duration in minutes, and the reader if the message names one.
- Resolve relative dates such as today, yesterday, last night, and weekday names against the current date in the configured timezone.
- Convert time ranges and natural phrases into minutes. For example, "3:15 to 3:45" becomes 30 minutes, "half an hour" becomes 30 minutes, and "an hour" becomes 60 minutes.
- If no title is named, store the title as "Unspecified".
- If no date is mentioned, use the current date.
- If the message contains no reading information, return an empty list of sessions.
- Discard any session whose duration is zero or cannot be determined as a positive number of minutes.

### 3. Reader resolution

- If the message explicitly names the reader, for example "Grandma read with him", use that name.
- If the message does not name a reader, use the name mapped to the sender's phone number.
- If the sender's number is not in the contact map, record the reader as "Unknown".

### 4. Data storage

- Store every session as a row in a SQLite table.
- Persist the original raw message and the sender's number for each session, for auditing.
- Record a timestamp for when the session was received.

### 5. Confirmation reply

- After logging, text the sender a confirmation that lists each logged session in plain language and shows the running summer total in minutes and in hours and minutes.
- If nothing could be parsed, reply with a friendly message that asks the sender to rephrase and gives one short example of a valid message.

### 6. Export

- Provide a CSV export that lists every session with columns for date, title, minutes, reader, and the logged-at timestamp, followed by a total row.
- Provide the export both as a web endpoint and as a command-line script that can be run on the server.
- The CSV must open cleanly in Excel and Google Sheets.

### 7. Dashboard

- Provide a read-only web page that shows all sessions in a table, most recent first, along with the summer total and the session count.

### 8. Access control for export and dashboard

- Protect the CSV export endpoint and the dashboard with a secret token supplied in the request.
- Reject any request to those endpoints that does not present the correct token.

### 9. Contacts

- Maintain a mapping from phone numbers to reader names in a simple editable file, for example JSON, so the owner can update it without changing code.
- Use full international phone number format, including the country code, as the keys.

## Data model

Store sessions with at least the following fields:

- A unique identifier.
- The session date as a calendar date.
- The title of the book or material.
- The duration in whole minutes.
- The reader's name.
- The sender's phone number.
- The original raw message text.
- The received-at timestamp.

## Configuration

All settings should come from environment variables or a local environment file, with sensible defaults where reasonable. Include at least the following:

- The AI provider API key.
- The export and dashboard secret token.
- The child's name for display on the dashboard.
- The timezone used to resolve dates and to timestamp sessions.
- The AI model identifier, so the owner can switch to a stronger model if parsing ever misses anything.
- A flag to turn Twilio signature validation on or off, plus the Twilio auth token used for that validation.
- The path to the SQLite database file.
- The path to the contacts file.

## Example messages and expected behavior

- Input "Tommy read Magic Tree House for 25 minutes today" should produce one session with that title, today's date, 25 minutes, and the reader taken from the sender map.
- Input "read 3:15 to 3:45 with grandma, Charlotte's Web" should produce one session of 30 minutes with the reader recorded as Grandma.
- Input "Dog Man 20 min and Frog and Toad 15 min before bed" should produce two sessions, one of 20 minutes and one of 15 minutes.
- Input "He read to me for half an hour last night, the Gruffalo" should produce one session of 30 minutes dated to yesterday.
- Input "thanks, see you tomorrow" should produce no sessions and a friendly reply asking the sender to rephrase.

## Non-functional requirements

- Hosting: the app must run as a long-lived web service on an inexpensive always-on server and stay available so the Twilio webhook can reach it at any time.
- Database: the app must use SQLite on a persistent path, and no session should ever be lost across restarts or redeploys.
- Security: secrets must never be committed to source control, the export and dashboard must be token protected, and Twilio validation should be available for production.
- Privacy: the data concerns a child, so the export link must be private and the data should not be exposed publicly.
- Cost: running the app should cost only a few dollars a month, including a Twilio number at roughly a dollar a month plus a small per-message fee, and minimal AI usage on a small model.
- Timezone: all date resolution and timestamps should use a single configured timezone.
- Reliability: a parsing failure or an AI error on one message must not crash the service, and the sender should still receive a helpful reply.

## Acceptance criteria

- A text sent to the configured number results in a stored session and a confirmation reply within a few seconds.
- A single text describing two sessions results in exactly two stored rows.
- A text that names a reader overrides the sender's default name.
- A text from a known number with no named reader uses the mapped name.
- A text from an unknown number is stored with the reader as "Unknown".
- Relative dates and time ranges are converted correctly as shown in the examples.
- A non-reading message produces no rows and a friendly reply.
- The CSV export and dashboard both reject requests without the correct token and both succeed with it.
- The CSV opens in a spreadsheet and ends with a correct total of all minutes.
- The service survives a restart with all previously logged sessions intact.

## Deployment expectations

- Provide clear setup instructions, including how to configure the Twilio number's inbound message webhook to point at the SMS endpoint.
- Provide instructions for at least one cheap always-on hosting path, including how to keep the process running and how to serve it over HTTPS, since Twilio requires a secure public URL.
- Make clear which configuration values must be set before first run.

## Suggested technical approach, not binding

- A lightweight Python web framework such as Flask, served by a production WSGI server such as gunicorn, is a good fit, though the developer may choose another stack that meets the constraints.
- The standard library SQLite module is sufficient for storage.
- Replying through a Twilio messaging response avoids the need for outbound message credentials.
- A small, fast AI model is enough for this parsing task, with the option to switch to a stronger model through configuration.

## Out of scope for the first version

- Multiple children in one account.
- A login system or multiple owner accounts.
- Editing or deleting sessions through a user interface.
- Integration with any specific Readathon fundraising platform.

## Open decisions to confirm before building

- Whether to track pages in addition to minutes. The current requirement is minutes only, but a pages field is easy to add if the Readathon program asks for it.
- Whether to send an automatic weekly summary text, for example every Sunday evening, with the week's total. This is optional and can be deferred.
- Whether the dashboard should also allow correcting a mistyped session, which would move session editing into scope.
