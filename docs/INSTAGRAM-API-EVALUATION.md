# Instagram API evaluation (M4b, spec §9.1)

**Status: Complete as a documentation deliverable. The live path is Unverified (external).**

This document answers the eleven questions `docs/UPGRADE-SPEC.md` §9.1 asks, using Meta's own
documentation only. Every fact below carries the document it came from and the date it was read.
Nothing here is inferred from a third-party blog, and nothing here claims a live integration has
worked — no authorised Meta app, access token or professional account was supplied for this
milestone, so the live path is recorded as **Unverified (external)**.

**Sources read on 2026-11-20:**

| # | Document | URL |
|---|---|---|
| D1 | Instagram Platform overview | <https://developers.facebook.com/documentation/instagram-platform/overview> |
| D2 | Content publishing guide | <https://developers.facebook.com/documentation/instagram-platform/content-publishing> |
| D3 | Resumable uploads guide | <https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads> |
| D4 | IG User — Media endpoint (reel & story specifications) | <https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media> |
| D5 | IG User — Content Publishing Limit endpoint | <https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit> |
| D6 | Instagram Platform error codes | <https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes> |
| D7 | IG User — Media Publish endpoint | <https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish> |
| D8 | IG Container reference | <https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container> |
| D9 | App Review | <https://developers.facebook.com/documentation/instagram-platform/app-review> |

Meta serves a plain-markdown rendering of each page by appending `.md` to the URL; that is how the
error-code table and the container status list were read exactly rather than paraphrased.

---

## 9.1.1 Current supported publishing API

The supported API is the **Instagram Platform Content Publishing API**, not a consumer-app
automation and not a private endpoint. D2 is titled "Content Publishing" and covers exactly four
publishing operations: **single images, videos, reels, and carousels**.

The API is reached through one of three **setups**, which differ in host, token and permissions
(D1, D2):

| Setup | Host | Access token | Page required? | Resumable upload? | Permissions |
|---|---|---|---|---|---|
| **Unified Login** *(recommended for new integrations)* | `graph.facebook.com` + `rupload.facebook.com` | Business Integration System User access token | No | **Yes** | `instagram_basic`, `instagram_content_publish` |
| **Facebook Login** | `graph.facebook.com` + `rupload.facebook.com` | Facebook Page access token | **Yes** | **Yes** | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` |
| **Instagram Login** | `graph.instagram.com` | Instagram User access token | No | **No** | `instagram_business_basic`, `instagram_business_content_publish` |

The publishing sequence is the same in all three (D2, D3):

1. **Create a container** — `POST /<IG_ID>/media`
2. **Put the media in the container** — either Meta fetches a public URL, or we upload the file
   to `rupload.facebook.com`
3. **Wait for the container** — `GET /<IG_CONTAINER_ID>?fields=status_code`
4. **Publish** — `POST /<IG_ID>/media_publish` with `creation_id`
5. **Read back** — `GET /<IG_MEDIA_ID>?fields=…`

**What AutoClip implements:** the single-clip path only. AutoClip publishes one rendered clip at
a time, so **carousels are out of scope** — and D6 documents an outright contradiction about how
many items a carousel may hold (see §9.1.9).

## 9.1.2 Account eligibility

D1 is explicit: *"Your app users must have an Instagram professional account. An Instagram
professional account can represent a business or creator."* The Platform serves **professional
accounts only** — Business and Creator. A personal account is not eligible for any of the
publishing endpoints.

D1 also records an access-level split:

- **Standard Access** is the default. It is sufficient when the app serves only accounts the
  owner has a role on. Meta warns: *"Because of the limited scope of Standard Access, some
  features might not work properly until your app has been granted Advanced Access."*
- **Advanced Access** is required once the app serves accounts the owner does not own or manage.
  It requires App Review and Business Verification.

**How AutoClip treats this.** AutoClip cannot read whether an account is professional from the
Graph API with the publishing permissions alone, so it does **not** claim to know. The eligibility
endpoint reports the documented requirements, what AutoClip could observe, and what is
**Unverified**. When Meta refuses a publish because the account is not professional, that refusal
is translated and shown — it is never guessed at locally.

## 9.1.3 Professional-account requirements

Two more conditions sit on top of "professional account" (D2, D4):

- **Page Publishing Authorization (PPA).** An Instagram professional account linked to a Page that
  requires PPA *cannot be published to* until PPA is completed. D2 notes there is no way to
  determine whether a Page requires PPA, and recommends telling app users to complete it
  proactively.
- **Two-factor authentication.** If the linked Page requires 2FA, the Facebook User must also have
  completed 2FA or the request fails (D4).

Both are **owner-controlled** and outside AutoClip's reach. They are documented here, surfaced in
the eligibility report, and not silently assumed away.

## 9.1.4 OAuth flow

D1 describes the flow for the Instagram-side logins:

1. The app user starts the login flow at Meta's **embed URL**. Meta opens an authorisation window
   and the user grants the requested permissions.
2. Meta redirects to the app's redirect URI with an **authorization code**, valid for **one hour**.
3. The app exchanges the code for a **short-lived access token** (valid **one hour**), an app-user
   id, and the list of permissions granted.
4. Before the short-lived token expires, the app exchanges it for a **long-lived access token**,
   valid **60 days**, which can be refreshed before it expires.

Meta's own note: *"If your app serves only your Instagram professional accounts, or accounts you
manage, you do not need to implement a login flow."* AutoClip is a single-owner desktop tool, so
it supports both: a browser sign-in for the general case, and a long-lived token the owner can
paste for the "only my own accounts" case.

**What AutoClip stores:** the long-lived token in the **OS keyring**, per account. Nothing
secret goes into SQLite or into a log line. The token is masked **entirely** wherever it might be
written down — no suffix fingerprint, because a partial mask still leaks the tail of a key.

## 9.1.5 Required permissions

The minimum set for publishing, per setup (D2, D5):

| Setup | Permissions |
|---|---|
| Unified / Facebook Login | `instagram_basic`, `instagram_content_publish` (+ `pages_read_engagement` for the Page-linked setup) |
| Instagram Login | `instagram_business_basic`, `instagram_business_content_publish` |

AutoClip requests **exactly** the publishing scopes for the chosen setup and nothing more. It does
**not** request comment, messaging, insights, hashtag-search or product-tagging permissions: none
of them is needed to publish, and asking for a permission the product does not use is a liability.

D4 notes one additional condition that has nothing to do with permissions: the app user must be
able to perform the `MANAGE` or `CREATE_CONTENT` task on the linked Page.

## 9.1.6 App review requirements

- **Standard Access** needs no review. It is the default and is enough for an app that serves
  only the owner's own accounts.
- **Advanced Access** requires **Meta App Review** (D9) and **Business Verification** (D1). Review
  submissions include a screencast showing the permission being used.
- D1 lists the permissions a **private app** may request approval for: only `instagram_basic` and
  `instagram_manage_comments`.

**Status here: not done, and owner-controlled.** Meta App Review and Business Verification are
outside what an agent can complete, and no Meta app exists for AutoClip yet. Until they are done,
AutoClip can only use Standard Access, which is sufficient for the owner's own accounts — which is
exactly the case AutoClip is built for. This is recorded as a residual, not as a blocker for the
automated work.

## 9.1.7 Quotas

Three separate limits apply, and AutoClip keeps them apart because they have different clocks:

| Limit | Value | Clock | Source |
|---|---|---|---|
| **Published posts** | see §9.1.9 — Meta's own documents disagree | rolling 24 h | D2, D5 |
| **Containers created** | **400** | rolling 24 h | D4 |
| **Container lifetime** | **24 hours**, then `EXPIRED` | — | D4 |
| **API calls** | `4800 × Number of Impressions` | rolling 24 h | D1 |

The API-call limit is Meta's *Business Use Case* rate limiting: *"An app's call count is unique for
each app and app user pair"*, so the allowance is per account, not per app.

**How AutoClip treats this.** The published-post limit is **read from the API** — `GET
/<IG_ID>/content_publishing_limit` returns `config.quota_total`, `config.quota_duration` and
`quota_usage` (D5) — rather than hardcoded from the prose. When Meta refuses a publish with
`code 9`, the upload is **queued to the reset** instead of being marked failed, the same way the
YouTube quota exhaustion is handled.

## 9.1.8 Media format restrictions

**Reels** (D4) — the format AutoClip publishes:

| Property | Requirement |
|---|---|
| Container | MOV or MP4 (MPEG-4 Part 14), **no edit lists, moov atom at the front** |
| Audio codec | AAC, **48 kHz maximum**, 1 or 2 channels |
| Video codec | **HEVC or H264**, progressive scan, closed GOP, 4:2:0 chroma subsampling |
| Frame rate | **23–60 FPS** |
| Picture size | **1920 columns maximum** (horizontal pixels) |
| Aspect ratio | between **0.01:1 and 10:1** (9:16 recommended) |
| Video bitrate | VBR, **25 Mbps maximum** |
| Audio bitrate | **128 kbps** |
| Duration | **3 seconds minimum, 15 minutes maximum** |
| File size | **300 MB maximum** |

**Stories** (D4): the same container/codec rules, but **60 s maximum, 3 s minimum, 100 MB maximum**.

**Images** (D4): JPEG only, 8 MB maximum, aspect ratio 4:5–1.91:1, width 320–1440.

**Caption** (D6): **2,200 characters**, **30 hashtags**, **20 @tags**.

**What AutoClip does.** Every one of these is checked against the *actual file* with `ffprobe`
before anything is sent — not guessed from the export settings. A clip that fails a limit is
refused with the measurement that failed ("the file is 41.2 Mbps; the limit is 25 Mbps"), so the
owner can fix it rather than guess why Meta rejected it. The `moov`-atom-at-the-front rule is
checked by reading the MP4 atom structure, because `ffprobe` does not report it.

## 9.1.9 Publishing restrictions

- **Professional accounts only** (§9.1.2).
- **PPA and 2FA** may block publishing (§9.1.3).
- **Carousels: out of scope.** AutoClip publishes single clips.
- **Trial reels** (`trial_params`) and **partnership ads** are not used.
- **Shopping tags and filters are not supported** by the API at all (D2).

**A contradiction in Meta's own documents, recorded rather than resolved by guessing.** The
publishing limit is stated three ways:

| Where | Says |
|---|---|
| D2, "Rate Limit" section | *"Instagram accounts are limited to **100** API-published posts within a 24-hour moving period."* |
| D2, carousel Limitations section | *"Accounts are limited to **50** published posts within a 24-hour period."* |
| D5, `content_publishing_limit` endpoint reference | *"The maximum number of IG Containers the app user can publish within the `quota_duration` time period (**currently `50`**)."* |

A second, separate contradiction: D2 and D4 say a carousel may hold **up to 20** items, while
Meta's own error `code 100 / subcode 2207028` says *"Carousels need at least 2 photos/videos and
**no more than 10** photos/videos."*

**How AutoClip treats this.** It **reads the live limit** from `GET
/<IG_ID>/content_publishing_limit` and shows what Meta reports, with the source named. It never
hardcodes 50 or 100 as if one of them were the truth. The carousel contradiction does not affect
AutoClip, because carousels are out of scope — but it is recorded here because a reader comparing
Meta's pages against this file should know the disagreement exists.

## 9.1.10 Error and rate-limit behaviour

Meta's error envelope carries `code`, `error_subcode`, `is_transient`, `error_user_title`,
`error_user_msg` and `fbtrace_id` (D6). The code table in D6 is the authority; AutoClip's
translation is in `backend/autoclip/instagram/errors.py` and is tested against the table below.

| Code | Subcode | What Meta says | AutoClip's decision |
|---|---|---|---|
| `-1` | `2207001` | Instagram server error | **Transient** — retry with backoff |
| `-1` | `2207032` | Create media failed | **Transient** — retry with backoff |
| `-1` | `2207053` | Unknown upload error | **Transient** — new container, then retry |
| `-2` | `2207003` | Took too long to download the media | **Transient** — retry |
| `-2` | `2207020` | The media has expired | **Transient** — new container, then retry |
| `1` | `2207057` | Thumbnail offset out of bounds | **Permanent** — the request is wrong |
| `4` | `2207051` | Publishing action suspected to be spam | **Permanent — not auto-retryable.** Meta's own advice is for the app user to confirm it is not spam; AutoClip does not retry into a spam block |
| `9` | `2207042` | Daily publishing limit reached | **Transient, queued to the reset** — "try again the following day" |
| `24` | `2207006` | Media not found (permission or expired token) | **Transient** — new container, then retry |
| `24` | `2207008` | The container does not exist or has expired | **Transient** — retry 1–2 times in 30 s–2 min, then a new container |
| `25` | `2207050` | The Instagram account is restricted | **Permanent — owner must act.** Meta's advice is to sign in to the Instagram app and complete the required action |
| `100` | `2207028` | Carousel item count out of range | **Permanent** (carousels are out of scope) |
| `100` | `2207040` | More than 20 @tags | **Permanent** |
| `352` | `2207026` | Video format not supported | **Permanent** — the file is not MOV/MP4 |
| `9004` | `2207052` | The media could not be fetched from the URI | **Transient** — the URI was not publicly reachable |
| `9007` | `2207027` | The media is not ready for publishing | **Transient** — poll the container and publish when it is `FINISHED` |
| `36000` | `2207004` | Image larger than 8 MiB | **Permanent** (images are out of scope) |
| `36001` | `2207005` | Image format not supported | **Permanent** (images are out of scope) |
| `36003` | `2207009` | Image aspect ratio out of range | **Permanent** (images are out of scope) |
| `36004` | `2207010` | Caption too long | **Permanent** — over 2,200 characters, 30 hashtags or 20 @tags |

**Container status** (D2, D8): `EXPIRED`, `ERROR`, `FINISHED`, `IN_PROGRESS`, `PUBLISHED`. Meta
recommends querying once per minute for no more than five minutes. AutoClip follows that: it
polls on that cadence and gives up after the documented window rather than polling forever.

**Resumable upload progress** (D3): the container's `video_status.uploading_phase` reports
`bytes_transferred`, and `processing_phase` reports the post-upload processing state. A partial
transfer resumes from that offset.

**A publish can succeed and still be partly wrong.** A successful `media_publish` can come back
with a `config_issue` — `CAPTION_NOT_ATTACHED` or `USER_TAGGING_FAILURE` — meaning the post went
up but part of the request was dropped. AutoClip records that on the upload row and reports it.
A publish that "worked" while silently losing the caption is not a success, and saying so is the
whole point.

---

## §9.2 Upload architecture

### What is officially supported

| Path | Official? | When |
|---|---|---|
| **Resumable upload of a local file** | **Yes** | *"This is available only for apps that have implemented Facebook Login for Business."* (D3) — so **Unified Login** and **Facebook Login**, and **not Instagram Login** |
| Upload from a public URL (`video_url` on the container) | Yes | All three setups (D2) |
| Upload from a public URL to `rupload.facebook.com` (`file_url` header) | Yes | Facebook Login for Business setups (D3) |

### The constraint that shapes the design

D2 is blunt: *"We cURL media used in publishing attempts, so the media must be hosted on a
publicly accessible server at the time of the attempt."* A **local file** only works through the
resumable upload protocol, and the resumable protocol only exists for Facebook Login for
Business.

So:

- **Unified Login / Facebook Login** → AutoClip uploads the local file directly to
  `rupload.facebook.com`, in chunks, resuming from the byte Meta says it has. **No cloud storage
  is introduced**, and none is needed: the file goes from the disk to Meta.
- **Instagram Login** → there is no official way to send a local file. AutoClip therefore
  **refuses** a local-file publish on that setup with a message saying why, rather than quietly
  uploading the file somewhere. If the owner supplies a **public URL** for the media themselves,
  AutoClip uses the documented `video_url` path and never sees the file.

AutoClip does **not** introduce a bucket, a CDN or any third-party host. The spec forbids it
without approval, and the resumable path means it is not needed. If the owner ever wants to use
the Instagram Login setup, the missing piece is *their own* public URL — a decision that is theirs,
not ours.

### Resumable upload protocol, as implemented

1. `POST https://graph.facebook.com/<version>/<IG_ID>/media` with `media_type=REELS`,
   `upload_type=resumable`, and the caption. Meta answers with `{"id": "<container>", "uri":
   "https://rupload.facebook.com/ig-api-upload/<version>/<container>"}` (D3, D4).
2. `POST <uri>` with `Authorization: OAuth <token>`, `offset: <byte>`, `file_size: <total>` and
   the file bytes as the body.
3. On a failure, `GET /<container>?fields=video_status` returns
   `video_status.uploading_phase.bytes_transferred`; the upload continues from there (D3).
4. `GET /<container>?fields=status_code` until it is `FINISHED`.
5. `POST /<IG_ID>/media_publish` with `creation_id=<container>`.

The chunk size, the session state and the resume logic live in
`backend/autoclip/instagram/publisher.py`, and are tested against doubles — including the case
where Meta's own `bytes_transferred` disagrees with what we recorded.

---

## §9.3 Publishing — what AutoClip supports, and what it refuses

| Spec item | Implementation |
|---|---|
| **Explicit account selection** | The upload row names the Instagram account. The token is that account's own keyring entry. The account is never inferred from "the first one connected" |
| **Media validation** | Every documented Reel limit is measured with `ffprobe` before anything is sent; the failing measurement is named |
| **Upload status** | `bytes_sent` / `total_bytes` are written to the row as the transfer proceeds; the UI shows the real figure, not a fabricated percentage |
| **Publishing status** | The container status (`IN_PROGRESS` / `FINISHED` / `ERROR` / `EXPIRED`) and the published media id are stored; a publish that lost part of the request is reported |
| **Error recovery** | Meta's error codes are translated into transient / permanent / owner-must-act, with the `fbtrace_id` kept for support |
| **Duplicate prevention** | Instagram has **no idempotency key** — the guarantee is local, the same way it is for YouTube: the worker refuses to send a clip that is already published to the same account |
| **Rate-limit handling** | The published-post limit is read live; `code 9` queues to the reset; 429 and 5xx back off |
| **Platform independence** | Instagram has its own tables and its **own worker queue**. An Instagram failure never cancels a YouTube upload, and the reverse is also true |

## What is deliberately not done

- **Carousels** — out of scope; AutoClip publishes one clip at a time.
- **Images and Stories** — AutoClip renders video. The validation code knows the image and story
  limits (so the refusal messages are accurate), but there is no image pipeline.
- **Trial reels, partnership ads, shopping tags, product tagging, comments, messaging,
  insights** — not needed to publish, and not requested as permissions.
- **Cloud storage** — not introduced, and not needed on the Facebook Login for Business path.
- **Any live claim** — without authorised credentials nothing here has been exercised against the
  real API. The live path is **Unverified (external)**.

## Residuals carried into M5

| Residual | Status | Action |
|---|---|---|
| The **live Meta path** — OAuth, container creation, resumable upload, publish, read-back | **Unverified (external)** — no Meta app, token or professional account was supplied | Lane B — run with an authorised test account |
| **Meta App Review and Business Verification** | **Not done** — owner-controlled, and only needed for Advanced Access | Owner — required before serving accounts AutoClip does not own |
| **PPA and Page 2FA** may block publishing for Page-linked accounts | **Unverified** — Meta documents that AutoClip cannot detect either | Owner — complete PPA proactively |
| The **published-post limit** is stated inconsistently by Meta | **Handled by reading the live limit** rather than hardcoding either figure | M5 — keep the live read |
| The **carousel item-count contradiction** (20 vs 10) | **Not applicable** — carousels are out of scope | — |
| The **`quota_total` value** may change without notice | **Handled** — the limit is read from the API each time | M5 — re-check the endpoint contract |
