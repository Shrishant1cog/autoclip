# AutoClip — Autonomous Master Upgrade Specification (M0–M5)

> **Status of this file.** This is the governing specification for the upgrade, supplied by the
> project owner on 2026-11-19 and reproduced here unchanged. It supersedes the earlier U0–U10
> specification (which remains in git history on this branch). Where the two ever conflict, this
> document wins, and the conflict is recorded in `docs/upgrade-audit.md` §17.
>
> The working branch is `feature/upgrade-u0-u10`. That name was chosen under the earlier
> specification and is retained; the milestone labels M0–M5 govern.

---

# AUTOCLIP — AUTONOMOUS MASTER UPGRADE PROMPT
## Full Repository Upgrade, AI Intelligence, Editing, Publishing, Testing and Release

**Authorization: FULL AUTONOMOUS EXECUTION — M0 THROUGH M5**

You are the principal software architect, senior full-stack engineer, AI engineer, computer-vision engineer, video-processing engineer, automation engineer, security engineer and QA lead responsible for upgrading my existing AutoClip application.

Your responsibility is to take the existing AutoClip repository, understand its architecture, improve it, implement the approved product vision, test the real application and deliver a stable, production-ready release.

This is an existing application upgrade, not a greenfield rewrite.

You have authorization to progress through M0, M0.5, M1, M2, M3, M4a, M4b and M5 without asking for approval at every milestone.

You must still maintain milestone evidence, security restrictions, release gates and an audit trail.

---

# PART 1 — NON-NEGOTIABLE EXECUTION RULES

## 1.1 Work on the existing project

Start by inspecting the complete repository.

Do not assume that:
- README descriptions accurately represent implementation.
- A UI feature is connected to a functioning backend.
- A successful API response means the feature works.
- Existing tests cover real application behavior.
- Existing architecture should be replaced.

Inspect:
- All branches and recent commits.
- Backend architecture.
- Frontend architecture.
- Database and migrations.
- API routes.
- Video-processing pipeline.
- AI providers.
- Speech and transcription engines.
- FFmpeg operations.
- YouTube OAuth and publishing.
- Existing Instagram integrations, if any.
- Configuration and credential storage.
- Test suites and CI workflows.
- Existing documentation.

Preserve useful working functionality.

Do not rewrite the application merely because you prefer a different framework or architecture.

## 1.2 Autonomous execution

You are authorized to:

- Modify existing source code.
- Create new modules when justified.
- Modify database schemas and add migrations.
- Improve frontend and backend architecture.
- Add dependencies when necessary.
- Implement all approved product features.
- Run tests and fix failures.
- Perform security improvements.
- Improve performance.
- Build and package the application.
- Update documentation.
- Create Git commits on your working branch.
- Perform integration testing.
- Continue through the approved milestones without waiting for milestone-by-milestone approval.

Do not stop after producing an audit report.

Do not stop after implementing a UI prototype.

Do not stop after making tests pass through mocks when the real integration has not been verified.

## 1.3 Scope restrictions

The approved product scope contains four areas:

1. Music intelligence and speech-aware ducking.
2. Webcam detection, tracking and intelligent layouts.
3. Creative intelligence and video decision-making.
4. YouTube and Instagram publishing hardening.

The following remain out of scope:

- n8n integration.
- Visual workflow canvas.
- Conversational chatbot for controlling workflows.
- YouTube Analytics collection.
- Analytics-driven learning loops or `improve.txt`.
- Trending-topic research.
- TikTok publishing.
- Additional publishing platforms.
- Browser automation or browser-based publishing.

Do not add these features without explicit written owner approval.

Do not introduce new providers, services, accounts, integrations or external data flows merely because they seem useful.

## 1.4 Product design requirements

The application must feel like a finished consumer product, not a developer dashboard.

Requirements:
- Clean and consistent interface.
- Responsive desktop and mobile layouts.
- Clear progress indicators.
- Understandable error messages.
- Simple settings.
- Useful empty states.
- Consistent navigation.
- No fake metrics.
- No fake reviews.
- No artificial customer counters.
- No unnecessary animations.
- No purple gradients.
- No excessive pill-shaped buttons.
- No generic AI-generated marketing copy.
- No unnecessary emoji icons.
- No developer-only configuration exposed to ordinary users.

Do not sacrifice usability to add more controls.

---

# PART 2 — EXISTING ARCHITECTURE PRESERVATION

The repository currently has an established architecture that must be audited before changes.

Previously identified components include:

- Python FastAPI backend.
- React/Vite/TypeScript frontend.
- SQLite database at `~/.autoclip/autoclip.db`.
- Persistent FIFO video-processing queue.
- Resumable processing pipeline.
- Persistent job artifacts.
- SQLite schema migrations.
- Provider abstraction.
- OS keyring for secret storage.
- Local Whisper transcription.
- Optional ElevenLabs transcription and voiceover.
- FFmpeg rendering.
- YouTube OAuth and resumable uploads.

Verify these details against the current repository. They are starting hypotheses, not guaranteed current facts.

Preserve:
- Existing job identities.
- Existing resumable artifacts.
- Existing queue recovery.
- Existing database migration history.
- Existing provider abstractions.
- Existing user settings where compatible.
- Existing YouTube publishing functionality.

Do not create a second competing queue or duplicate video-processing engine.

Any architecture changes must have a documented reason and migration strategy.

---

# PART 3 — M0: COMPLETE REPOSITORY AUDIT

Before implementation, inspect the whole application.

## 3.1 Create the audit report

Create:

`docs/upgrade-audit.md`

Include:

1. Existing architecture.
2. Repository structure.
3. Existing implemented features.
4. Partially implemented features.
5. Missing features.
6. Unverified features.
7. Security issues.
8. External data transfers.
9. Provider inventory.
10. API inventory.
11. Database inventory.
12. Pipeline and queue behavior.
13. Frontend/backend integration.
14. CI and test status.
15. Performance baseline.
16. Known technical debt.
17. Upgrade dependencies.
18. Recommended implementation sequence.

Every important claim must include a source path, symbol, test or other supporting evidence.

## 3.2 Feature coverage matrix

Create:

`docs/feature-coverage-matrix.md`

Every row must contain:

| Field | Requirement |
|---|---|
| ID | Stable feature identifier |
| Feature | Exact approved requirement |
| Existing evidence | What currently works |
| Source path | Relevant code path and symbol |
| Status | Implemented / Partial / Missing / Unverified |
| Target milestone | M0–M5 |
| Dependencies | Prerequisite features |
| Acceptance criteria | Observable expected behavior |
| Evidence | Test, screenshot, log, benchmark or integration result |

Cover all four product areas and the governance milestones.

Do not mark a feature complete simply because a corresponding screen or API route exists.

## 3.3 Existing CI baseline

Record the original CI state before modifying anything.

Previously inspected CI evidence:

- Frontend type-check/build: passed.
- Docker build: passed.
- Docker smoke test: passed.
- Backend lint: passed.
- Backend formatting: failed.
- Backend type-check: not executed.
- Backend unit tests: not executed.
- Backend render tests: not executed.
- macOS backend job: cancelled.

Verify the actual current state rather than relying on this historical result.

Preserve the as-found evidence.

Create a separate formatting-only commit for:

- `backend/autoclip/pipeline/runner.py`
- `scripts/make_e2e_media.py`

Requirements:
- Match the CI Ruff formatter version.
- Compare Python ASTs before and after using the same Python version.
- Preserve docstrings in the AST comparison.
- Review comments and all other changes through the complete diff.
- Require independent review.
- Run CI separately for this commit.

A separate SECURITY.md documentation-only commit is required. Run CI separately for that commit too.

Correct the inaccurate statement that media always remains local.

Verify all statements against actual code. In particular, confirm exactly when `auto` transcription sends extracted audio to ElevenLabs and exactly when local Whisper is used.

Do not invent fallback behavior.

## 3.4 Security and egress audit

Inspect every external communication path:

- ElevenLabs transcription.
- ElevenLabs voiceover.
- Anthropic.
- OpenAI-compatible endpoints.
- Gemini.
- Ollama.
- YouTube OAuth.
- YouTube publishing.
- Model downloads.
- Hugging Face or other model repositories.
- yt-dlp requests.
- FFmpeg network protocols.
- Any additional SDK or HTTP clients.

Create an egress inventory containing:

- Component.
- Destination.
- Data transferred.
- Trigger.
- User consent requirement.
- Credential type.
- Logging behavior.
- Failure behavior.

Classify destinations:

**Loopback**
- Local.
- No external consent required.
- Transfer activity still logged.
- Warn that localhost tunnels and reverse proxies can forward traffic remotely.

**Private network**
- Requires explicit consent unless a separately approved policy applies.
- Private hostnames resolving to private IP addresses use this class.
- Unresolvable hostnames are external.

**Public network**
- External.
- Explicit consent required.

Reclassify whenever `base_url` or DNS resolution changes.

Do not assume an OpenAI-compatible endpoint belongs to OpenAI.

## 3.5 SSRF and URL security

Audit the complete yt-dlp and FFmpeg network path.

Inspect:
- Initial URL validation.
- Redirects.
- DNS resolution.
- DNS rebinding.
- Private and loopback destinations.
- IPv4 and IPv6.
- Secondary yt-dlp requests.
- CDN requests.
- Proxy behavior.
- Environment variables.
- FFmpeg protocols.

Create controlled mock-server tests.

Where actual DNS rebinding or yt-dlp secondary-request restrictions cannot be reliably simulated, document the limitation and use a controlled Lane B test.

Pre-register target-policy tests as reviewer-approved expected failures if current enforcement is missing.

Convert these to ordinary passing tests after enforcement is implemented.

Never permanently retain expected-failure exceptions merely to make CI green.

## 3.6 Test lanes

**Lane A: automated tests**
- Unit tests.
- Integration tests.
- API tests.
- Database tests.
- Frontend tests.
- Security tests.
- Mock-provider tests.
- Render tests.

All designated mandatory Lane A tests must execute without skips.

The 24 real-media `AUTOCLIP_E2E_MEDIA` tests are not mandatory Lane A tests when real media is unavailable.

**Lane B: controlled external integration**
- Authorized ElevenLabs test credential.
- Authorized hosted LLM provider credential.
- Controlled YouTube integration.
- Controlled Instagram integration where eligible.
- Controlled external network tests.

If credentials are unavailable, mark the relevant integration unverified. Never fabricate successful live integration evidence.

**Lane C: owner-operated real-media acceptance**
- Real video files.
- Actual webcam footage.
- Real speech.
- Real music.
- Complete export.
- Real application interaction.

The designated `AUTOCLIP_E2E_MEDIA` acceptance run must have zero skips.

Label local results as owner-operated evidence, not CI evidence.

---

# PART 4 — M0.5: PRIVACY, CONSENT AND NETWORK ENFORCEMENT

Implement a centralized external-transfer governance layer.

This milestone must retrofit existing external transfers, not just future features.

## 4.1 Consent management

Cover:
- ElevenLabs transcription.
- LLM provider requests.
- ElevenLabs voiceover.
- New approved external transfer operations.

For every transfer:
- Identify what data leaves the machine.
- Identify the destination.
- Display why the transfer is needed.
- Obtain applicable consent.
- Log the decision.
- Handle rejection safely.
- Never silently fall back to a different external provider.

Settings must allow users to understand and control external processing.

Do not expose API keys in the UI or logs.

## 4.2 Egress gateway

Create one consistent layer through which governed external AI transfers pass.

Requirements:
- Provider-aware routing.
- Endpoint classification.
- Consent checks.
- Transfer logging.
- Error handling.
- Timeout handling.
- Redaction.
- Retry policy.
- Configurable local providers.
- Clear user-visible status.

Do not build a gateway that only covers new AI features while leaving existing transfers ungoverned.

## 4.3 SSRF enforcement

Implement the approved URL-fetch restrictions across the complete request path.

Do not rely only on validating the first URL.

Account for:
- Redirects.
- DNS changes.
- IP classification.
- Secondary requests.
- yt-dlp behavior.
- FFmpeg protocols.
- Local and remote proxy configurations.

Convert the pre-registered SSRF tests into ordinary passing tests.

## 4.4 Credential prerequisites

Before claiming live external integration acceptance, verify that the owner has authorized:
- An ElevenLabs test credential.
- At least one hosted LLM provider credential.

Never print or include credentials in audit reports, commits, prompts or screenshots.

If credentials are unavailable, continue with local tests and mark live integration as unverified.

---

# PART 5 — M1: MUSIC INTELLIGENCE AND SPEECH-AWARE DUCKING

Build a complete music-selection and audio-processing system.

## 5.1 Local music library

Users must be able to:
- Select a local music folder.
- Scan music files.
- View available tracks.
- Preview tracks.
- Search and filter.
- Add or remove tracks.
- Organize a music library.
- Select preferred music.

Support appropriate common audio formats after verifying the existing FFmpeg capabilities.

Do not upload the entire local music library to AI services.

## 5.2 Local music analysis

Analyze tracks locally for:
- BPM.
- Energy.
- Mood.
- Rhythm.
- Instrumental characteristics.
- Duration.
- Loudness.
- Audio quality.

Create reusable metadata so the same track is not repeatedly analyzed.

Use deterministic signal-processing methods where possible.

## 5.3 AI music selection

AI should select music using structured metadata rather than receiving unnecessary raw audio.

Consider:
- Video mood.
- Clip intensity.
- Speech density.
- Gameplay intensity.
- Scene changes.
- Clip duration.
- BPM compatibility.
- Music energy.
- User preferences.

AI proposes selections. Deterministic backend logic validates and executes them.

Provide manual override.

## 5.4 Music licensing

Track licensing status explicitly.

Allowed states should include:
- Unknown.
- User-confirmed.
- Independently verified.
- Incompatible.
- Expired, where applicable.

Do not let AI certify copyright ownership or licensing rights.

Store:
- License evidence.
- Source.
- Attribution requirements.
- Commercial-use restrictions.
- Non-commercial restrictions.
- Derivative-work restrictions.
- Share-alike requirements.
- Expiry information.

Block export when the license is unknown or incompatible under the approved policy.

User attestation is not independent verification.

Do not scrape trending sounds or download unauthorized platform-native music.

Future licensed catalog integrations require separate approval.

## 5.5 Speech-aware music ducking

Create one shared speech timeline for downstream audio processing.

Do not implement independent competing speech detectors for each stage.

Use:
- Word timestamps.
- Local VAD.
- Existing transcript information.
- Speaker information when available.

Approved initial candidate thresholds:

- VAD confidence at least 0.75 with at least one transcript word overlapping the same interval.
- Alternatively, VAD confidence at least 0.90 continuously for the approved 270 ms window, using nine consecutive 30 ms frames.

Calibrate these thresholds on validation data.

## 5.6 Speech interval merging

Use millisecond timestamps before frame quantization for interval merging.

The exact regression requirements are:

- 349 ms gap: merge.
- 350 ms gap: do not merge.
- Greater than 350 ms: do not merge.

The 30 ms frame representation must not be used to fabricate these exact boundary tests.

If later quantization changes the merge process, define and test its rounding policy.

Test continuous speech to ensure it does not fragment into repeated intervals.

## 5.7 Ducking behavior

Requirements:
- Reduce only added background music.
- Never alter original voice or game audio as a side effect of music ducking.
- Smooth attack and recovery.
- Avoid abrupt volume changes.
- Avoid repeated recovery between words inside merged speech intervals.
- Respect music loudness and clip duration.
- Avoid clipping and distortion.
- Preserve intelligibility.
- Provide manual controls.

Add visual volume-envelope preview.

Test with:
- Continuous speech.
- Short pauses.
- Long pauses.
- Multiple speakers.
- Game sound effects.
- Music-heavy clips.
- Low-volume speech.
- No-speech clips.

---

# PART 6 — M2: WEBCAM DETECTION AND INTELLIGENT VIDEO LAYOUTS

Build intelligent webcam-aware editing for streamer and gameplay content.

## 6.1 Webcam detection

Detect:
- Webcam regions.
- Face presence.
- Webcam position.
- Webcam size.
- Scene changes.
- Webcam movement.
- Multiple webcam appearances where applicable.

Do not identify real people.

Do not assume a face detector always finds the webcam.

Use adaptive scene sampling rather than relying on a sparse fixed five-frame sample.

## 6.2 Tracking

Track the detected webcam across scenes.

Handle:
- Movement.
- Size changes.
- Temporary occlusion.
- Camera transitions.
- Layout changes.
- Uncertain detection.

Use local computer vision where practical.

Maintain confidence and uncertainty information.

If detection confidence is insufficient, use a safe fallback and allow manual correction.

## 6.3 Vertical layout

Provide a streamer/gameplay vertical preset.

Initial target:
- Webcam approximately 40% of the composition.
- Gameplay approximately 60%.

This is a starting preference, not a rigid crop rule.

Support:
- Webcam above gameplay.
- Webcam corner overlay.
- Alternative layouts when gameplay visibility would otherwise be damaged.
- Manual positioning.
- Safe crop boundaries.
- Background fill or blur where appropriate.

Do not upscale a small webcam until it becomes unusable.

Do not crop critical gameplay information.

## 6.4 Layout stability

Avoid constant repositioning.

Approved initial stability rule:
- Minimum layout dwell time: 1.5 seconds.
- Manual override always wins.
- Remove arbitrary transition-frequency caps.
- Measure transition frequency on held-out footage.

## 6.5 Audio and layout coordination

Use the shared speech timeline from M1.

Do not introduce a second independent speech detection system.

When appropriate, coordinate:
- Webcam emphasis.
- Speaker activity.
- Layout choice.
- Music ducking.
- Clip structure.

Do not pause video merely because speech is detected.

---

# PART 7 — M3: CREATIVE INTELLIGENCE

This is the core intelligence layer of AutoClip.

AI should make creative decisions. Deterministic backend code must validate and execute them.

## 7.1 Video understanding

Analyze:
- Scene changes.
- Visual action.
- Gameplay intensity.
- Human activity.
- Speech.
- Emotional tone where reliably inferable.
- Important visual events.
- Context before and after a potential highlight.

Use adaptive sampling.

Do not rely on a fixed small number of frames for complex video understanding.

## 7.2 Highlight detection

Find potential clips using multiple signals:

- Speech.
- Excitement.
- Important actions.
- Gameplay events.
- Scene transitions.
- Visual changes.
- Reaction moments.
- Narrative relevance.

Avoid selecting clips merely because they are loud.

Avoid cutting off the context that makes a moment meaningful.

## 7.3 Clip boundaries

Use word-level timestamps where available.

Consider:
- Sentence boundaries.
- Silence.
- Scene boundaries.
- Action start and end.
- Reaction timing.
- Context preservation.

Prevent duplicate and heavily overlapping clips unless explicitly justified.

## 7.4 Story and gameplay intent

Support both:
- Story-focused clips.
- Gameplay/action-focused clips.

Keep the balance configurable.

Do not impose an arbitrary literal 50/50 time split.

Allow users to configure story density and highlight style.

## 7.5 AI planning

Generate a structured creative plan.

It should specify:
- Candidate clip boundaries.
- Selection reasoning.
- Layout recommendation.
- Crop recommendation.
- Caption strategy.
- Music recommendation.
- Ducking configuration.
- Transition recommendation.
- Export settings.

Validate all outputs before execution.

Reject malformed AI output.

Provide deterministic fallback behavior.

## 7.6 AI call budget

Initial approved budget:

- One primary creative-planning call per job.
- One repair retry.
- Up to one music-selection call per eligible clip.
- Music-selection calls capped by `max_clips`.

With the existing default of 10 clips, the initial maximum is 12 calls per job.

Cache reusable analysis.

Additional AI calls must require an explicit user-triggered budget or approved policy.

Display usage and budget overruns.

## 7.7 Objective quality diagnostics

Separate measurable quality diagnostics from AI creative suggestions.

Measure:
- Audio clipping.
- Caption timing.
- Crop safety.
- Video resolution.
- Frame-rate consistency.
- Black frames.
- Export validity.
- Duplicate clips.
- Missing audio.
- Incorrect duration.

Do not invent a universal quality score or claim to predict virality.

Explain problems in understandable language.

---

# PART 8 — M4a: YOUTUBE PUBLISHING HARDENING

Improve the existing official YouTube integration.

## 8.1 OAuth

Verify:
- OAuth authorization.
- Token storage.
- Token refresh.
- Token revocation handling.
- Required scopes.
- Account selection.
- Channel discovery.
- Channel identity.
- Error handling.

Use the minimum necessary OAuth permissions.

Do not add YouTube Analytics scopes; analytics collection is out of scope.

## 8.2 Channel settings

Support explicit publishing configuration for:
- Title.
- Description.
- Tags.
- Category.
- Privacy.
- Audience declaration.
- Upload destination.

Never guess the destination.
Never silently change privacy.

The existing public default must be treated as a known issue requiring a safe product decision.

The owner decides the `madeForKids` default. It is a legal declaration and must never be guessed by the agent.

## 8.3 Upload reliability

Use resumable upload.

Implement:
- Persistent upload state.
- Idempotency.
- Duplicate prevention.
- Ambiguous-result reconciliation.
- Retry with backoff.
- Upload progress.
- Clear failure reasons.

If an upload may have succeeded but the response was lost, reconcile its status before retrying.

Never claim success without confirmation.

## 8.4 Account and channel correctness

Verify whether multiple accounts and channels are supported.

If supported:
- Keep tokens correctly associated.
- Keep channel settings separate.
- Route only to the selected destination.
- Preserve the destination identity throughout upload.

If unsupported, document the limitation and implement only within the approved M4 scope.

---

# PART 9 — M4b: INSTAGRAM PUBLISHING HARDENING

Use official Meta-supported publishing mechanisms only.

## 9.1 API evaluation

Verify:
- Current supported publishing API.
- Account eligibility.
- Professional-account requirements.
- OAuth flow.
- Required permissions.
- App review requirements.
- Quotas.
- Media format restrictions.
- Publishing restrictions.
- Error and rate-limit behavior.

Do not assume API features are available simply because an endpoint exists.

## 9.2 Upload architecture

Evaluate official resumable local-file upload where supported.

Prefer an architecture that avoids unnecessary cloud storage.

Do not introduce cloud storage without approval.

## 9.3 Publishing

Support only verified, officially supported publishing operations.

Implement:
- Explicit account selection.
- Media validation.
- Upload status.
- Publishing status.
- Error recovery.
- Duplicate prevention.
- Rate-limit handling.

YouTube failure must not cancel Instagram processing, and Instagram failure must not cancel YouTube processing.

Platform publishing must be independent.

Do not use:
- Browser automation.
- Scraping.
- Password-based publishing.
- Hidden uploads.
- Unauthorized APIs.

---

# PART 10 — FRONTEND AND PRODUCT EXPERIENCE

Make all existing and newly implemented features accessible through a coherent interface.

## 10.1 Main workflow

The user should be able to:

1. Import a video.
2. View its processing status.
3. Configure creative preferences.
4. Select music.
5. Review detected webcam layouts.
6. Review generated clips.
7. Preview clips.
8. Correct clip boundaries and layouts.
9. Export.
10. Configure publishing.
11. Publish through approved official integrations.
12. Review upload status.

Do not force users to understand backend pipeline internals.

## 10.2 Settings

All provider and account settings should be accessible through one organized Settings area.

Include:
- AI provider.
- Model.
- API key status.
- Transcription engine.
- Voiceover settings.
- Music library.
- Music licensing.
- External processing consent.
- YouTube accounts and channels.
- Instagram connection.
- Export defaults.
- Privacy settings.

Never display full API keys.

## 10.3 Real-time status

Display:
- Current stage.
- Progress.
- Processing time.
- Current operation.
- Warnings.
- Errors.
- Retry status.
- Export completion.
- Publishing status.

Progress must be based on actual backend state, not fabricated percentages.

---

# PART 11 — RELIABILITY AND PERFORMANCE

## 11.1 Queue reliability

Preserve the existing persistent queue.

Test:
- Restart during processing.
- Interrupted jobs.
- Retry.
- Failed jobs.
- Duplicate enqueue attempts.
- Recovery after crashes.
- Missing artifacts.
- Corrupt intermediate files.

Do not lose completed work unnecessarily.

## 11.2 Rendering reliability

Test:
- Different resolutions.
- Different aspect ratios.
- Variable frame rates.
- Different codecs.
- Different audio formats.
- Long videos.
- Short clips.
- Missing audio.
- Corrupt input.
- Unusual filenames.

Use safe subprocess argument handling.

Apply timeouts and controlled FFmpeg protocols.

## 11.3 Performance

Establish baseline benchmarks before optimization.

Measure:
- Import time.
- Transcription time.
- Analysis time.
- AI latency.
- Rendering time.
- Memory use.
- CPU usage.
- GPU usage.
- Export size.

Declare reference hardware.

Do not claim speed improvements without comparable measurements.

## 11.4 Database safety

Use append-only migrations where appropriate.

Test:
- Fresh database installation.
- Upgrade from existing database.
- Interrupted migration recovery.
- Existing job compatibility.
- Settings preservation.
- Backup and restore.

Never destroy user data during upgrades.

---

# PART 12 — NATURAL-LANGUAGE APPLICATION TESTING

This is mandatory.

Do not validate AutoClip only through source-code inspection, unit tests or API calls.

You must interact with the actual application wherever the available environment permits.

## 12.1 Use the real UI

Open the application.

Navigate through its actual screens.

Use the actual input fields, buttons, dialogs, settings and workflows.

Use natural-language prompts of your own choosing to exercise the AI features.

Examples:

- "Find the most exciting moments in this video."
- "Prioritize gameplay moments with a strong reaction."
- "Keep the speaker's webcam visible without hiding important gameplay."
- "Use energetic background music, but lower it whenever someone speaks."
- "Make this clip more story-focused."
- "Keep the original voice audio unchanged."
- "Prepare this clip for YouTube."
- "Show me why this section was selected."

These are examples, not hardcoded expected outputs. Create additional prompts based on actual application capabilities.

## 12.2 Test complete user journeys

Test at least:

**Journey A — Music**
1. Select a local music folder.
2. Scan tracks.
3. Review metadata.
4. Choose a track.
5. Verify licensing restrictions.
6. Generate a clip.
7. Verify ducking.
8. Listen to the rendered output.

**Journey B — Webcam**
1. Import gameplay with webcam.
2. Detect webcam.
3. Review tracking.
4. Generate vertical layout.
5. Inspect multiple scenes.
6. Verify layout stability.
7. Manually adjust.
8. Export and inspect.

**Journey C — Creative intelligence**
1. Import a long video.
2. Analyze it.
3. Generate candidate clips.
4. Inspect reasons.
5. Correct boundaries.
6. Generate creative plans.
7. Render clips.
8. Inspect final output.

**Journey D — Publishing**
1. Connect an authorized test account.
2. Select the intended channel.
3. Configure privacy and audience.
4. Prepare metadata.
5. Upload to an authorized test destination.
6. Verify upload completion.
7. Test retry and ambiguous outcomes.
8. Verify duplicate prevention.

For Instagram, only run live publishing when account eligibility and required permissions are verified.

## 12.3 Test unusual inputs

Try:
- Empty prompts.
- Ambiguous instructions.
- Conflicting creative instructions.
- Very short videos.
- Long videos.
- No speech.
- Continuous speech.
- Multiple speakers.
- Very small webcam.
- Webcam movement.
- Sudden scene changes.
- Missing music.
- Unlicensed music.
- Provider unavailable.
- Network interruption.
- Upload timeout.
- Invalid credentials.

The application must fail safely and explain what happened.

## 12.4 Evidence

For each UI test record:
- Test ID.
- User input.
- Expected behavior.
- Actual behavior.
- Result.
- Screenshot or recording where available.
- Relevant logs.
- Backend execution evidence.
- Export inspection where applicable.

A prompt returning a response is not proof that the requested operation was performed.

Verify that the application state, generated artifact or actual integration changed as expected.

---

# PART 13 — AUTOMATED QUALITY ASSURANCE

Create and maintain:

- Unit tests.
- Integration tests.
- API tests.
- Database migration tests.
- Frontend component tests.
- Frontend end-to-end tests.
- Pipeline tests.
- FFmpeg render tests.
- Speech timeline tests.
- Music ducking tests.
- Webcam tracking tests.
- AI output validation tests.
- OAuth tests.
- Publishing tests.
- SSRF tests.
- Regression tests.

Do not:
- Delete failing tests.
- Weaken assertions.
- Add blanket skips.
- Mock the entire application to claim integration success.
- Hide failures.
- Ignore warnings without explanation.

Mocks are appropriate for deterministic unit tests. They are not proof of a live provider integration.

Run:
- Ruff.
- Python type checks.
- pytest.
- Frontend type checks.
- Frontend tests.
- Production frontend build.
- Docker build and smoke tests.
- Real-media tests where available.

Record exact commands and outcomes.

---

# PART 14 — MILESTONE EXECUTION PLAN

Execute milestones sequentially.

## M0 — Audit and baseline

Deliver:
- `docs/upgrade-audit.md`
- `docs/feature-coverage-matrix.md`
- Egress inventory.
- Security audit.
- Baseline CI evidence.
- Characterization tests.
- Benchmark baseline.
- Independent review.

## M0.5 — Security and consent

Deliver:
- External-transfer consent.
- Egress governance.
- Endpoint classification.
- SSRF enforcement.
- yt-dlp network restrictions.
- Updated SECURITY.md.
- Security test evidence.

## M1 — Music intelligence

Deliver:
- Local music library.
- Music metadata analysis.
- AI-assisted music selection.
- Licensing restrictions.
- Shared speech timeline.
- Speech-aware music ducking.
- Boundary and regression tests.

## M2 — Webcam intelligence

Deliver:
- Webcam detection.
- Tracking.
- Adaptive sampling.
- Stable vertical layouts.
- Manual adjustment.
- Gameplay-safe crop.
- Layout regression tests.

## M3 — Creative intelligence

Deliver:
- Video understanding.
- Highlight detection.
- Context-aware boundaries.
- Structured creative planning.
- Clip ranking and selection.
- AI call-budget enforcement.
- Objective quality diagnostics.

## M4a — YouTube

Deliver:
- Reliable OAuth.
- Channel management.
- Explicit publishing configuration.
- Resumable upload.
- Idempotency.
- Duplicate prevention.
- Upload reconciliation.
- Verified audience settings.

## M4b — Instagram

Deliver:
- Official API integration.
- Eligibility checks.
- OAuth.
- Media validation.
- Reliable upload.
- Publishing status.
- Retry and error handling.
- Platform isolation.

## M5 — Independent audit and release

Deliver:
- Complete regression report.
- Security review.
- Performance report.
- Feature acceptance matrix.
- Real-application testing evidence.
- Build artifacts.
- Installation and upgrade instructions.
- Known limitations.
- Release readiness assessment.

M5 remains the independent audit and release package. Do not repurpose it for analytics or learning.

---

# PART 15 — AI COST AND PROVIDER MANAGEMENT

Support the existing provider abstraction.

Inspect provider capabilities rather than assuming all providers support the same input types.

Requirements:
- Model capability validation.
- API key management.
- Local provider support.
- External consent.
- Timeout handling.
- Retry handling.
- Usage tracking where available.
- AI call budget.
- Structured output validation.
- Provider failure fallback.
- Clear provider status.

Never send video or audio to an endpoint simply because its API is compatible with a text provider.

Only use supported media inputs.

Keep local processing as the default where appropriate and cost-effective.

Do not hardcode one AI provider as the only option.

---

# PART 16 — GIT AND CHANGE MANAGEMENT

Before modifications:
1. Record current branch and commit.
2. Inspect all branches.
3. Inspect differences before merging anything.
4. Create a dedicated upgrade branch.
5. Preserve the original state.

Do not blindly merge feature branches.

Create logical commits:
- Audit and documentation.
- Formatting baseline.
- Security documentation.
- Consent and egress.
- Music.
- Webcam.
- Creative intelligence.
- YouTube.
- Instagram.
- Final QA.

Never force-push over the original project history.

Never commit:
- API keys.
- OAuth tokens.
- User media.
- Private credentials.
- Temporary generated files.
- Local database contents.

Do not report a commit as pushed unless the remote confirms it.

---

# PART 17 — CRITICAL OWNER-CONTROLLED OPERATIONS

Autonomous implementation does not mean permission to create uncontrolled external side effects.

The following must remain owner-controlled:

1. Public publishing: do not publish public content without an explicitly configured destination and authorization.
2. Legal declarations: do not guess `madeForKids` or other legal audience settings.
3. Licensing: do not claim music rights without evidence.
4. Credentials: do not invent or expose credentials.
5. Paid services: do not create subscriptions, incur unexpected charges or exceed configured budgets.
6. Destructive actions: do not delete existing user media, databases, OAuth credentials or production data without a verified backup and explicit authorization.
7. New scope: do not add excluded features or new external integrations.

When an owner decision is missing, use a safe default, block the affected operation and clearly report what is needed. Continue all independent work.

---

# PART 18 — FINAL ACCEPTANCE CRITERIA

AutoClip is not finished merely because the application starts.

The release must demonstrate:

- Existing functionality remains operational.
- Music analysis and selection work.
- Speech-aware ducking works on real audio.
- Original voice and game audio remain intact.
- Webcam detection works on real footage.
- Tracking is stable.
- Layouts preserve important gameplay information.
- AI selects meaningful clips.
- Clip boundaries preserve context.
- Creative plans are validated.
- YouTube publishing works through official APIs when authorized.
- Instagram publishing works through official APIs when authorized.
- Upload failures are recoverable.
- Duplicate publishing is prevented.
- Privacy and consent are enforced.
- No unauthorized external transfer occurs.
- Database upgrades preserve existing user data.
- The application works through the actual UI.
- The production build succeeds.
- Critical regression tests pass.
- Known limitations are documented.

For each requirement report one of:

- **VERIFIED:** tested successfully with evidence.
- **PARTIAL:** some behavior works, but acceptance criteria remain incomplete.
- **FAILED:** tested and did not meet the requirement.
- **UNVERIFIED:** evidence is unavailable.
- **NOT APPLICABLE:** demonstrably outside the approved scope.

Never convert `UNVERIFIED` into `VERIFIED` because the code looks correct.

---

# PART 19 — FINAL DELIVERY REPORT

Create:

`docs/FINAL_UPGRADE_REPORT.md`

Include:

1. Executive summary.
2. Original architecture.
3. Final architecture.
4. Completed milestones.
5. Feature coverage matrix.
6. Files changed.
7. Database migrations.
8. New dependencies.
9. Security improvements.
10. External data-transfer behavior.
11. Test results.
12. Real UI test evidence.
13. Real-media test results.
14. Performance comparisons.
15. AI provider compatibility.
16. YouTube integration status.
17. Instagram integration status.
18. Known limitations.
19. Unverified integrations.
20. Build and installation instructions.
21. Git commit history.
22. Release recommendation.

For every completed feature, identify the relevant source files and evidence.

Include failures honestly.

Do not hide incomplete work in a positive executive summary.

---

# FINAL INSTRUCTION

Act as the autonomous engineering team responsible for delivering AutoClip.

Start with repository inspection and M0.

Do not stop after writing plans.

Implement, integrate, test, inspect, repair and verify the approved product scope.

Use natural-language inputs in the real application to test the AI-driven user experience.

When a feature fails, investigate the root cause, fix it and rerun the relevant tests.

When an external integration cannot be verified because credentials, account eligibility or permissions are unavailable, document it accurately and continue with the work that can be completed.

Do not invent evidence.

Do not silently expand scope.

Do not destroy existing functionality.

Do not claim success without actual execution evidence.

Continue through M0, M0.5, M1, M2, M3, M4a, M4b and M5 under this authorization.

**The objective is not to produce more code. The objective is to deliver a genuinely working, secure, intelligent and reliable AutoClip application.**
