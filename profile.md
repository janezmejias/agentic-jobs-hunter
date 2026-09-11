<!--
STABLE CORPUS. This whole file goes into the cached block of the prompt, so:

  1. Change it as little as possible. Every byte you touch invalidates the cache
     and the next run pays for the full prefix again.
  2. It is the ONLY thing the model may claim about you. What isn't here doesn't
     get written.

The source is profile/Profile.pdf. If you update the PDF, update this by hand:
the PDF's raw text is fine for reading, not for a model to select from.

The CARDS are the core mechanism. The model does NOT send a summary of you: it
reads the posting, picks one or two cards that fit, and writes about those.
That's why each card carries tags and a concrete result.

Size matters here: Haiku 4.5 only caches prefixes of 4096 tokens or more, and
below that it silently doesn't cache. Run `python3 draft.py --diagnose` after
editing this file.
-->

# Juan Anez — profile corpus

## Identity

AI Engineer. Twelve years building Java/Spring platforms for banking, telecom,
healthcare and retail. For the last two years, putting LLM agents inside that
same class of system and keeping them running in production.

Positioning, in his own words: *"Most AI features don't fail because of the
model. They fail because the backend was never designed for non-deterministic
systems."* He builds AI inside platforms that already have auth, audit trails,
PII rules, SLAs and someone on call.

Based in Bogotá, Colombia (UTC-5). Works in English with distributed teams
across the US and Latin America. Spanish native, English professional working.

## Signature

Juan Anez
janezmejias.09@gmail.com
linkedin.com/in/janezmejias

## How to pick what goes in an email

1. Read the posting. Identify what the team actually needs: a domain (fintech,
   telecom, health), a stack (AWS, GCP, Java, Python), or a problem shape
   (latency, cost, eval quality, scale, compliance).
2. Choose ONE card below that matches, two at most. Lead with it.
3. Quote the card's concrete result. Never generalize it into "experience in X".
4. If nothing matches well, use CARD-AGENT-PLATFORM and be brief. A short honest
   email beats a stretched one.
5. Never list all the cards. Never write a résumé summary.

---

## CARD-AGENT-PLATFORM
**Tags:** llm agents, production, aws, serverless, multi-tenant, whatsapp, voice,
chatbots, genai, applied ai, startup, founding
**Role:** Lead AI Engineer at Vitzi tech (Yatendi), June 2024 – present.

Built and still operates a multi-tenant agent platform on AWS serverless —
Lambda, DynamoDB, EventBridge Scheduler, SQS FIFO, Secrets Manager — handling
WhatsApp, Instagram and voice conversations for live businesses. Not a pilot:
real customers, real money, he is the one on call.

**Use when:** the posting is about shipping LLM agents that real users touch,
about owning a system end to end, or about a small team where the engineer
operates what they build.

## CARD-VOICE-LATENCY
**Tags:** voice, latency, streaming, realtime, telephony, performance,
optimization, llm inference
**Role:** same platform, Vitzi tech.

Voice agents were unusable above roughly 2 seconds of turn latency. He built a
custom LLM-streaming bridge over the telephony provider and cut the turn budget
to a ~1 second target.

**Use when:** the posting mentions voice, real-time, streaming, latency budgets,
or inference performance.

## CARD-EVAL-LOOP
**Tags:** evals, llm evaluation, quality, experimentation, observability,
regression testing, canary, prompt engineering, mlops
**Role:** same platform, Vitzi tech.

Agent quality was anecdotal, so he built a closed loop: every run logged with a
configuration fingerprint, deterministic checks separated from judgment calls,
and every prompt or model change shipped as an experiment against a regression
bank of replayed real conversations, promoted by canary.

His line on it: *"'the prompt got better' is not a claim you can defend without
one."*

**Use when:** the posting mentions evals, LLM observability, quality regression,
experimentation, prompt iteration, or anything about knowing whether a model
change helped.

## CARD-UNIT-ECONOMICS
**Tags:** cost, unit economics, token cost, efficiency, margin, scale
**Role:** same platform, Vitzi tech.

Cost per conversation is a hard engineering constraint on that platform: it has
to stay below what the customer pays in subscription. He designs against that
ceiling rather than discovering it at the invoice.

**Use when:** the posting mentions cost per request, token spend, margins,
efficiency at scale, or inference cost.

## CARD-MESSAGING-RULES
**Tags:** whatsapp, meta, messaging, rate limits, integrations, api constraints,
queues, reliability
**Role:** same platform, Vitzi tech.

Meta's messaging rules break naive senders: limits computed at business-portfolio
level, template category audits, and error codes that must never be retried. He
built the send worker around rate-limited SQS FIFO with those rules encoded,
instead of retry loops.

**Use when:** the posting involves third-party API constraints, messaging
platforms, rate limiting, or queueing under hostile external rules.

## CARD-TELECOM-TMF
**Tags:** telecom, tmf, gcp, cloud run, spanner, microservices, java, spring boot,
architecture, greenfield, api design
**Role:** AI Software Engineer at Enghouse Networks, March 2023 – present.

An American operator needed its systems exposed as TMF-compliant APIs, with no
existing platform to build on. He led the design and delivery of fourteen
Java/Spring Boot microservices on GCP Cloud Run implementing TMF standards.

Chose Cloud Spanner over a conventional relational store because the address
model needed GEOGRAPHY columns, SCD-2 history and horizontal reach across
regions — and designed the schema forward-compatible with the next phase, so the
wireline expansion landed without a migration.

**Use when:** the posting is telecom, large-scale microservices, GCP, distributed
databases, API standards, or greenfield platform design.

## CARD-PII-SECURITY
**Tags:** security, pii, compliance, privacy, gdpr, tokenization, kms, iam,
secrets, regulated, healthcare, fintech
**Role:** Enghouse Networks.

Customer PII was flowing through logs and environment variables. He moved it
behind Cloud DLP tokenization with versioned HMAC keys, KMS-managed encryption
and per-service least-privilege IAM, and pulled every secret out of environment
variables into Secret Manager.

**Use when:** the posting mentions compliance, PII, regulated data, security
review, or any domain where data handling is audited.

## CARD-EVENT-RELIABILITY
**Tags:** events, pubsub, kafka, outbox, dead letter, reliability, distributed
systems, data consistency
**Role:** Enghouse Networks.

Made event delivery survivable: Pub/Sub with dead-letter queues and a
transactional outbox, so a downstream failure stops being a lost event.

**Use when:** the posting mentions event-driven architecture, streaming,
exactly-once concerns, or data consistency across services.

## CARD-BANKING
**Tags:** banking, fintech, payments, money, backbase, oauth2, saga, compliance,
java, spring
**Role:** digital banking work on Backbase DBS.

Arrangements, transactions, limits and maker-checker approval matrices. Spring
Cloud Gateway, OAuth2/OIDC, and saga patterns for money flows that cannot end
half-done.

**Use when:** the posting is fintech, banking, payments, or anything where a
partial failure moves money.

## CARD-PAYMENTS-SCALE
**Tags:** payments, high traffic, retail, scale, mobile, full stack
**Role:** Senior Software Engineer at Emida Technologies, Jan 2017 – May 2022.

Design and development of high-traffic web and Android applications for payments
and retail, with full SDLC engineering practice — coding standards, code review,
source control, build processes.

**Use when:** the posting emphasizes high traffic, payments volume, or long-run
production ownership.

## CARD-TECH-LEAD
**Tags:** leadership, tech lead, mentoring, team, delivery, stakeholders,
staff, principal
**Role:** Technical Lead at 24/7 Software, Nov 2021 – Dec 2022.

Led delivery across multiple projects: estimation, coordinating frontend and
backend release integration, working with BA teams and clients on usability and
roadmap, prioritizing to release on schedule, and removing impediments.

**Use when:** the posting is a lead, staff, principal or founding role, or
mentions mentoring and cross-team coordination.

## CARD-AI-ASSISTED-ENGINEERING
**Tags:** ai coding, developer tools, code review, engineering practice
**Role:** how he works, across projects.

He uses AI to write code and reviews every line at the boundaries that matter:
schemas, money, auth, and anything that deletes. Those it does not touch
unreviewed.

**Use when:** the posting is about AI developer tooling, or explicitly asks how
the candidate works with AI.

## CARD-ENTERPRISE-JAVA
**Tags:** legacy, modernization, migration, java, oracle, weblogic, soap, jbpm,
solr, enterprise, integration, monolith
**Role:** Java Software Engineer at Indra (2016–2017) and Fundación Petrociencia
(2013–2016).

Large-scale enterprise Java: Oracle Database and WebLogic 12c, SOAP and RPC
services alongside REST, Spring MVC and Spring REST, jBPM for automating
business workflows and decisions, Apache Solr for search. At Petrociencia this
was an integrated system for well handling and analysis, including automated
workflow management for reservoir studies and document/norm protection for
integrated studies.

**Use when:** the posting involves modernizing or integrating with an existing
enterprise estate — SOAP services, an Oracle/WebLogic stack, workflow engines,
or search — rather than greenfield work. This is also the card that shows the
twelve years are real and not padding.

## CARD-FULLSTACK
**Tags:** full stack, frontend, angular, react, typescript, ui, web apps,
mobile, android, product engineer
**Role:** across 24/7 Software, Emida Technologies and Fundación Petrociencia.

Front end alongside the backend, not instead of it: Angular and React web
applications, plus Android apps at Emida for high-traffic payments and retail.
At 24/7 Software he coordinated frontend and backend release integration and
worked directly with BA teams and clients on usability and roadmap.

**Use when:** the posting is full-stack, product engineering, or a small team
where the same person owns the interface and the service behind it.

---

## General facts (safe to state)

- Twelve years of software engineering; roughly two years focused on LLM agents
  in production.
- Domains: banking, telecom, healthcare, retail, payments.
- Primary stack: Java, Spring Boot, Spring AI. Also Angular, React, Python.
- Cloud: AWS (Lambda, DynamoDB, EventBridge, SQS, Secrets Manager) and GCP
  (Cloud Run, Spanner, Pub/Sub, Cloud DLP, KMS, Secret Manager).
- Data: PostgreSQL, MySQL, Oracle, DynamoDB, Spanner.
- Practice: trunk-based development, GitLab MR gates, dependency and container
  scanning in CI, Kubernetes, microservices, RAG.
- Certifications: Introduction to Data Science (statistical programming in R),
  R Programming, Design Patterns & SOLID Principles, Software Architecture Case
  Studies, Amazon EC2.
- Education: BS Computer Science, Universidad Rafael Belloso Chacín (2008–2011).
  MSc Computer Applications, University of Zulia (2018–2020).
- Availability: full-time remote, or contractor. Full overlap with US hours.

## Never claim

- Any employer, client, product, number or certification not listed above.
- Specific revenue, headcount, user counts or latency figures beyond the ~1s
  voice turn target and the ~2s threshold it replaced.
- Familiarity with the reader's company, product or funding.
- Security clearance, US work authorization, or a visa status. He is in Colombia.
- Fluency claims beyond: Spanish native, English professional working.

---

## How to open (rotate these; never reuse an opener)

A cold email is read in the first line. Good openers name something specific
from the posting. Patterns that work, in rough order of strength:

1. Name the exact constraint the posting mentions, then say he has hit it.
   *"The turn-latency line is what made me write."*
2. Name the role and the one thing he'd bring.
   *"About the Founding AI Engineer role you posted — what I'd bring is the
   unglamorous half."*
3. Name a shared problem shape.
   *"You're putting agents into a system that already has an on-call rotation.
   That's the work I do."*
4. When the posting is thin, say so plainly and be short.
   *"Your Hacker News post didn't say much about the stack, so I'll be brief."*

## Phrases that must never appear

These read as template and cost more than they earn:

- "I hope this email finds you well" / "I hope you're doing well"
- "I am excited to apply" / "I am thrilled" / "I would love the opportunity"
- "I came across your posting" / "I stumbled upon"
- "passionate about", "cutting-edge", "state-of-the-art", "leverage",
  "synergy", "game-changing", "world-class", "rockstar", "ninja"
- "I believe I would be a great fit" — say what fits instead
- "Please find my resume attached" — the attachment speaks for itself
- "Thank you for your time and consideration"
- Any sentence praising the company's mission, product or vision
- Any sentence that starts "As a seasoned..."

## Shape of a good email

- 90–160 words. Three short paragraphs at most.
- Paragraph 1: why this posting, in one or two sentences. Specific.
- Paragraph 2: the card. One concrete thing he built, with its result.
- Paragraph 3: one line of context (the twelve years, or availability), then a
  simple next step as a question.
- Signature block from § Signature, nothing more.
- No bullet lists. No headers. No markdown. Plain prose, like a person typing.


## Shape of a follow-up

A follow-up is not the first email again. It is shorter and it adds something.

- 40 to 80 words. One paragraph, two at most.
- Reference the earlier email in half a sentence, without reproaching anyone for
  not replying. Never "just checking in", never "bumping this", never "I wanted
  to follow up".
- Add ONE thing that was not in the first email: a different card, a sharper
  version of the same point, or a concrete question about their stack.
- End with an easy out: it is fine if the role is filled or not a fit.
- Same signature block.

### Example 4 — follow-up, seven days later

> Hi Sarah,
>
> I wrote last week about the Voice AI role. One thing I left out: the part that
> actually took the longest wasn't the streaming bridge, it was the eval loop
> behind it — replaying real conversations against every prompt change so we
> could tell a regression from noise.
>
> If the role is filled or I'm off base, no problem at all. If not, I'd still
> like to hear how you're measuring quality today.
>
> Juan Anez
> linkedin.com/in/janezmejias

---

## Exemplar emails

These set the register: what he opens with, how long, how it ends. Match the
tone, never the wording — every email must be different.

### Example 1 — posting mentions voice agents and latency

> Hi Sarah,
>
> I saw the Voice AI Engineer opening at Loop. The turn-latency line is what made
> me write.
>
> I lead the agent platform at Vitzi tech — WhatsApp and voice agents on AWS
> serverless for live businesses. Voice was unusable for us above about two
> seconds per turn, so I built a custom LLM-streaming bridge over our telephony
> provider and brought the turn budget down to a ~1s target. That one number
> changed whether people stayed on the call.
>
> Twelve years of Java/Spring behind that, mostly in banking and telecom, which
> is where I learned to treat an agent like any other system that pages someone
> at 3am.
>
> Would it be useful to talk? I'm in Bogotá, UTC-5, full overlap with US hours.
>
> Juan Anez
> linkedin.com/in/janezmejias

### Example 2 — posting is a generalist AI engineer role at a small team

> Hi,
>
> About the Founding AI Engineer role you posted on Hacker News.
>
> I build and operate a multi-tenant agent platform at Vitzi tech: WhatsApp,
> Instagram and voice, on Lambda, DynamoDB and SQS FIFO, for businesses that are
> actually paying. What I'd bring to a founding role is the unglamorous half —
> every run logged with a config fingerprint, prompt changes shipped as
> experiments against a regression bank of replayed conversations, and a cost
> per conversation that has to stay under the subscription price.
>
> Before this, twelve years of Java and Spring in banking and telecom.
>
> Happy to walk through the eval setup if it's relevant. I'm remote from
> Colombia, UTC-5.
>
> Juan Anez
> linkedin.com/in/janezmejias

### Example 3 — the posting says almost nothing

> Hi,
>
> Your Hacker News post didn't say much about the stack, so I'll keep this short
> and you can tell me if it's worth more.
>
> I run a multi-tenant agent platform at Vitzi tech — WhatsApp and voice agents
> on AWS serverless, for businesses that actually pay for it. Twelve years of
> Java and Spring before that, mostly banking and telecom. The thing I'm good at
> is the part after the demo works: evals, cost per conversation, and what
> happens at 3am.
>
> If you're hiring for that, I'd like to hear more. Remote from Colombia, UTC-5.
>
> Juan Anez
> linkedin.com/in/janezmejias
