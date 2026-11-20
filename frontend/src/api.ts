/**
 * Typed client for the AutoClip API.
 *
 * Same-origin throughout: the server hands out the built bundle, so there is no
 * base URL to configure and no CORS to negotiate.
 */

export interface Source {
  id: string
  type: string
  title: string
  url: string | null
  filename: string | null
  channel: string | null
  duration_s: number
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  has_video: boolean
  created_at: string
}

export type JobStatus = 'queued' | 'running' | 'failed' | 'done' | 'cancelled'

export interface Job {
  id: string
  source_id: string
  status: JobStatus
  current_stage: string
  progress: number
  error: string | null
  provider: string
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  source: Source | null
}

export interface UploadRecord {
  id: string
  export_id: string
  clip_id: string
  channel_row_id: string
  status: 'pending' | 'uploading' | 'done' | 'failed' | 'skipped' | 'needs_reconciliation'
  video_id: string | null
  title: string
  description: string
  tags: string[]
  privacy: string
  error: string | null
  watch_url: string
  created_at: string
  updated_at: string
  /** The audience declaration that was sent: 'false' or 'true'. */
  made_for_kids: string
  /** The privacy that was asked for. */
  requested_privacy: string
  /** The privacy YouTube reports after the upload. */
  actual_privacy: string
  /** The YouTube channel id the video went to. */
  destination_channel_id: string
  /**
   * True when the video is on YouTube but is not visible the way it was
   * asked to be — YouTube forced it private, for instance.
   */
  published_but_not_as_asked: boolean
  /** How many bytes YouTube has. The worker writes it after every chunk. */
  bytes_sent: number
  /** The size of the file, so the progress has something to be a fraction of. */
  total_bytes: number
  /** How many times the upload has been tried. */
  attempts: number
  /** When the next attempt is due. Empty when it is due now. */
  next_attempt_at: string
  /** The progress as a percentage, or 0 when it is not known. */
  progress_percent: number
  /** What we found when we went looking for the upload. */
  reconcile_status: '' | 'confirmed' | 'evidence' | 'not_uploaded' | 'unknown'
  /** The sentence shown to the owner about the lookup. */
  reconcile_detail: string
  /** When the lookup happened. */
  reconciled_at: string
  /**
   * True when the upload may or may not have reached YouTube and the
   * owner has to look. It was not sent again and it was not called
   * published.
   */
  needs_reconciliation: boolean
}

/** How much of YouTube's daily API quota is left. */
export interface YouTubeQuota {
  day: string
  units_used: number
  uploads_started: number
  uploads_finished: number
  limit: number
  remaining: number
}

export interface ExportRecord {
  id: string
  clip_id: string
  ratio: string
  style: string
  size_bytes: number
  created_at: string
  download_url: string
  upload: UploadRecord | null
  uploads: UploadRecord[]
}

export type ClipStatus = 'candidate' | 'kept' | 'discarded' | 'exported' | 'invalid'

export interface Clip {
  id: string
  job_id: string
  rank: number
  start_s: number
  end_s: number
  duration_s: number
  start_word: number
  end_word: number
  title: string
  hook: string
  score: number
  reason: string
  status: ClipStatus
  user_trimmed: boolean
  caption_style: string
  ratio: string
  /** The music this clip ended up with. Empty when it has none. */
  music_track_id: string
  /** Whose choice it was: "user", "ai" or "deterministic". */
  music_source: string
  /** Why that track was chosen, in plain words. */
  music_reason: string
  /**
   * The objective quality measurements.
   *
   * These are measurements, not a score: there is no single quality
   * number, because there is no honest way to fold ten different
   * measurements into one.
   */
  diagnostics: ClipDiagnostics | null
  /**
   * Where this clip would be published, and why.
   *
   * Six fields: the category, the channel, the reason, the rule, the
   * confidence and whether it was a fallback.
   */
  routing: RoutingDecision | null
  exports: ExportRecord[]
  validation: {
    ok: boolean
    checks: { name: string; ok: boolean; detail: string }[]
  } | null
}

/**
 * Where a clip goes, and why — in six fields.
 *
 * The confidence is the classifier's own figure, reported by the model
 * that read the transcript. It is not a quality score, and there is no
 * quality score anywhere.
 */
export interface RoutingDecision {
  clip_id: string
  /** What the clip was classified as. */
  category: string
  /** The channel *row* id, not the YouTube channel id. */
  channel_row_id: string
  /** The YouTube channel id. */
  channel_id: string
  channel_title: string
  /** The sentence that explains the decision. */
  reason: string
  rule_id: string
  /** The rule, as a person reads it: its name, or its keyword. */
  rule: string
  rule_name: string
  rule_keyword: string
  confidence: number
  /** True when the decision did not come from a rule. */
  fallback: boolean
  /** Why it was a fallback: "no rule matched", "no classification". */
  fallback_reason: string
  /** The other channel rows the same rule sends the clip to. */
  extra_channel_ids: string[]
  /** Whether the destination's own auto-upload is on. */
  auto_upload: boolean
  created_at: string
}

/** One measurement from the objective quality report. */
export interface ClipDiagnostic {
  name: string
  title: string
  ok: boolean
  /** What was measured, in words or as a number. */
  measured: string
  /** The problem, in a sentence. Empty when the measurement is fine. */
  detail: string
  /**
   * False when the measurement could not be made. An unmeasurable thing
   * is not the same as a correct one, and the two are never conflated.
   */
  available: boolean
}

/** The objective quality report for one clip. */
export interface ClipDiagnostics {
  ok: boolean
  diagnostics: ClipDiagnostic[]
  /** Present when the report was made on demand rather than at export. */
  state?: string
}

/** A clip in the cross-job library, with the context needed to group it. */
export interface LibraryClip extends Clip {
  source_title: string
  job_status: JobStatus
}

export interface Word {
  text: string
  start: number
  end: number
  speaker: string | null
}

export interface CropKeyframe {
  t: number
  x: number
  y: number
}

export interface CropSegment {
  start_s: number
  end_s: number
  width: number
  height: number
  keyframes: CropKeyframe[]
  strategy: 'track' | 'wide' | 'general'
  zoom: number
  fit: boolean
}

/** Mirrors autoclip.pipeline.reframe.croppath.CropPath. */
export interface CropPath {
  source_width: number
  source_height: number
  segments: CropSegment[]
}

export interface CaptionStyle {
  key: string
  label: string
  description: string
  preview: {
    font: string
    primary: string
    accent: string | null
    outline: string
    outlineWidth: number
    allCaps: boolean
    sizeRatio: number
    marginRatio: number
    boxed: boolean
    animation: string
    maxWords: number
  }
}

export interface ProviderStatus {
  name: string
  available: boolean
  detail: string
  models: string[]
  requires_key: boolean
  has_key: boolean
}

export interface Settings {
  active_provider: string
  providers: Record<string, { model: string; base_url: string | null }>
  whisper: { model: string; compute_type: string; language: string; diarization: boolean }
  transcription?: {
    engine: 'auto' | 'elevenlabs' | 'local'
    elevenlabs_model: string
    diarize: boolean
    voiceover: 'off' | 'muxed'
    voice_id: string
  }
  clips: {
    min_duration_s: number
    max_duration_s: number
    max_clips: number
    /** Absent on a server older than M3. */
    story_density?: number
    highlight_style?: 'auto' | 'story' | 'action'
  }
  ingest: {
    ytdlp_format: string
    cookies_from_browser: string
    prefer_youtube_captions: boolean
  }
  export: {
    ratio: string
    caption_style: string
    loudness_lufs: number
    prefer_hardware_encoder: boolean
    crf: number
    write_srt: boolean
    music_track: string
    music_volume: number
    music_ducking: boolean
    ducking_amount_db: number
    /** Absent on a server older than M2. */
    layout?: 'auto' | 'above' | 'corner' | 'gameplay_only'
    webcam_height_frac?: number
    webcam_position?: LayoutPosition
    webcam_corner_frac?: number
  }
  /** Absent on a server older than Phase 16. */
  resources?: {
    ffmpeg_threads: number
    max_parallel_ffmpeg: number
    work_retention_days: number
    export_retention_days: number
    raw_retention_days: number
    cleanup_on_start: boolean
    max_output_tokens: number
    max_llm_calls_per_job: number
  }
  youtube: {
    client_id: string
    redirect_uri: string
    auto_upload: boolean
    privacy: 'private' | 'unlisted' | 'public'
    category_id: string
    channel_id: string
    channel_title: string
    channel_url: string
    connected_at: string
  }
  insecure_secret_storage: boolean
  keys_present: Record<string, boolean>
  youtube_secret_present: boolean
}

export interface YouTubeStatus {
  configured: boolean
  connected: boolean
  auto_upload: boolean
  client_id: string
  redirect_uri: string
  privacy: 'private' | 'unlisted' | 'public'
  channel_id: string
  channel_title: string
  channel_url: string
  connected_at: string
  /** The audience declaration: '' (not decided), 'false' or 'true'. */
  made_for_kids: string
}

/** What the publishing policy would do for a destination. */
export interface YouTubePolicy {
  privacy: string
  made_for_kids: boolean
  /** '' (not decided), 'false' or 'true'. */
  made_for_kids_state: string
  audience_decided: boolean
  category_id: string
  account_id: string
  channel_row_id: string
  destination_channel_id: string
  destination_title: string
  audience_options: { value: string; label: string }[]
  privacy_options: string[]
}

export interface SystemStatus {
  ready: boolean
  python_version: string
  platform: string
  ffmpeg_version: string | null
  has_libass: boolean
  nvenc_works: boolean
  accel: string
  gpu_name: string | null
  compute_type: string
  diarization_available: boolean
}

/** One area of AutoClip's storage. */
export interface ResourceDirectory {
  name: string
  path: string
  size_bytes: number
  size_human: string
  file_count: number
}

/** What one job consumed. Every number is measured, not estimated. */
export interface JobResourceUsage {
  job_id: string
  status: string
  title: string
  llm_calls: number
  llm_input_tokens: number
  llm_output_tokens: number
  llm_total_tokens: number
  ffmpeg_runs: number
  ffmpeg_seconds: number
  export_bytes: number
  windows_skipped: number
  updated_at: string
}

export interface ResourceOverview {
  disk: {
    directories: ResourceDirectory[]
    database_bytes: number
    database_human: string
    total_bytes: number
    total_human: string
  }
  limits: {
    ffmpeg_threads: number
    max_parallel_ffmpeg: number
    work_retention_days: number
    export_retention_days: number
    raw_retention_days: number
    cleanup_on_start: boolean
    max_output_tokens: number
    max_llm_calls_per_job: number
  }
  usage: {
    totals: {
      llm_calls: number
      llm_input_tokens: number
      llm_output_tokens: number
      llm_total_tokens: number
      ffmpeg_runs: number
      ffmpeg_seconds: number
      export_bytes: number
      export_human: string
      windows_skipped: number
    }
    jobs: JobResourceUsage[]
  }
}

export interface CleanupReport {
  removed_files: number
  removed_directories: number
  freed_bytes: number
  freed_human: string
  details: string[]
  changed: boolean
}

export interface JobSettingsOverrides {
  provider?: string
  whisper_model?: string
  language?: string
  diarization?: boolean
  min_duration_s?: number
  max_duration_s?: number
  max_clips?: number
  caption_style?: string
  ratio?: string
}

/** An API error carrying the server's message and its actionable hint. */
export class ApiError extends Error {
  hint: string
  status: number
  /** The server's stable failure code (auth, quota, rate_limit, …). */
  code: string
  /** Whether trying the same thing again could plausibly work. */
  retryable: boolean

  constructor(message: string, status: number, hint = '', code = '', retryable = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.hint = hint
    this.code = code
    this.retryable = retryable
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let hint = ''
    let code = ''
    let retryable = false
    try {
      const body = await response.json()
      const detail = body.detail
      if (typeof detail === 'string') {
        message = detail
      } else if (detail && typeof detail === 'object') {
        // The ingest endpoints return {message, hint} so the UI can show the
        // fix alongside the failure.
        message = detail.message ?? message
        hint = detail.hint ?? ''
      }
      // The unified error shape (Phase 15) adds a stable code and whether a
      // retry is worth attempting.
      if (typeof body.code === 'string') code = body.code
      if (typeof body.retryable === 'boolean') retryable = body.retryable
      if (!hint && typeof body.hint === 'string') hint = body.hint
    } catch {
      /* Response had no JSON body; the status line is the best we have. */
    }
    throw new ApiError(message, response.status, hint, code, retryable)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

// -- Workflows & batches (Phase 6/7) ----------------------------------------

export interface WorkflowNodeSpec {
  type: string
  name: string
  category: string
  description: string
  inputs: string[]
  output: string
  config_schema: Record<string, string>
  optional: boolean
  max_retries: number
}

export interface WorkflowNodeSpecAlias {
  /** A registered node type in the palette. */
  spec: WorkflowNodeSpec
}

export interface WorkflowNode {
  id: string
  type: string
  enabled?: boolean
  config?: Record<string, unknown>
  position?: { x: number; y: number }
}

export interface WorkflowEdge {
  from: string
  to: string
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface Workflow {
  id: string
  name: string
  description: string
  definition: WorkflowDefinition
  version: number
  active: boolean
  created_at: string
  updated_at: string
}

export interface WorkflowRunNode {
  node_id: string
  node_type: string
  status: string
  attempt: number
  input: unknown
  output: unknown
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  job_id: string | null
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  trigger: string
  started_at: string
  finished_at: string | null
  error: string | null
  workflow_name: string
  nodes?: WorkflowRunNode[]
}

export interface WorkflowRunResult {
  run_id: string
  status: string
  nodes: { node_id: string; status: string; error: string | null }[]
}

export interface BatchItem {
  id: string
  batch_id: string
  source_id: string
  job_id: string | null
  position: number
  status: 'pending' | 'processing' | 'done' | 'failed' | 'skipped' | 'cancelled'
  error: string | null
  created_at: string
  updated_at: string
  source_title?: string
}

export interface BatchProgress {
  total: number
  pending: number
  processing: number
  done: number
  failed: number
  skipped: number
  cancelled: number
}

export interface MusicTrack {
  name: string
  path: string
}

// -- Music library (M1) -------------------------------------------------------

/**
 * The licence states. `verified` is deliberately absent: independent
 * verification is not something a user can assert about their own files.
 */
export type LicenseState = 'unknown' | 'user_confirmed' | 'incompatible' | 'expired'

export interface MusicLicense {
  track_id: string
  state: LicenseState
  source: string
  evidence: string
  attribution: string
  commercial_use: boolean
  non_commercial: boolean
  derivative: boolean
  share_alike: boolean
  expires_at: string
  verified_by: string
  verified_at: string
  updated_at: string
}

/** What the local measurement found. Every number is measured, not guessed. */
export interface MusicAnalysis {
  duration_s: number
  sample_rate: number
  channels: number
  bpm: number
  bpm_confidence: number
  energy: number
  rms_dbfs: number
  peak_dbfs: number
  loudness_lufs: number
  mood: string
  mood_scores: Record<string, number>
  beat_regularity: number
  groove_strength: number
  spectral_centroid_hz: number
  spectral_rolloff_hz: number
  percussive_ratio: number
  harmonic_ratio: number
  stereo_width: number
  clipping_ratio: number
  dc_offset: number
  noise_floor_dbfs: number
  dynamic_range_db: number
}

export interface MusicLibraryTrack {
  id: string
  path: string
  folder_id: string
  name: string
  title: string
  artist: string
  tags: string[]
  format: string
  size_bytes: number
  mtime: number
  duration_s: number
  analysis_at: string
  analysis: MusicAnalysis
  excluded: boolean
  favourite: boolean
  created_at: string
  updated_at: string
  license: MusicLicense
  license_allowed: boolean
  license_reason: string
  license_warnings: string[]
  /**
   * The shapes this track has, derived from the measurements.
   *
   * A track carries more than one: a short, sparse, steady loop is
   * three things at once. Absent on a server older than M3.
   */
  formats?: string[]
}

export interface MusicFolder {
  id: string
  path: string
  added_at: string
}

export interface MusicScanReport {
  folders: number
  found: number
  added: number
  skipped: number
  errors: string[]
}

export interface MusicEnvelope {
  job_id: string
  start_s: number
  end_s: number
  duck_db: number
  points: { t: number; gain: number }[]
  intervals: {
    start_ms: number
    end_ms: number
    confidence: number
    source: string
    speaker: string | null
  }[]
  /** "not measured yet" when the job has no speech timeline. */
  state?: string
}

/** The filters the library can be narrowed by. */
export interface MusicFilters {
  q?: string
  mood?: string
  min_bpm?: number
  max_bpm?: number
  /** Absent on a server older than M3. */
  min_energy?: number
  max_energy?: number
  format?: string
  licence?: string
  favourite?: boolean
  tag?: string
}

// -- Creative intelligence (M3) ------------------------------------------------

/**
 * A shape a track can have, derived from the measurements.
 *
 * The name is a measurement, not a mood: "steady" means the beat
 * regularity is at least 0.55, and the `measured` line says so.
 */
export interface MusicFormat {
  value: string
  title: string
  description: string
  /** The measurement the name comes from, in plain words. */
  measured: string
}

/** One stored music choice, at one scope. */
export interface MusicPreference {
  scope: 'global' | 'source' | 'clip'
  scope_id: string
  /** The chosen track. Empty when nothing is chosen here. */
  track_id: string
  /** True when this scope says "no music at all". */
  none: boolean
  updated_at: string
}

/**
 * The music choice that applies, and where it came from.
 *
 * The scopes are separate: a clip's choice survives the source's choice
 * being changed, and clearing one scope does not clear another. The most
 * specific scope wins.
 */
export interface MusicPreferences {
  clip_id: string
  source_id: string
  /** The effective choice. Empty when the automatic selection applies. */
  track_id: string
  /** True when the effective choice is "no music at all". */
  none: boolean
  /** Which scope the effective choice came from. Empty when none applies. */
  scope: string
  global: MusicPreference
  source: MusicPreference
  clip: MusicPreference
}

/** One allowance and what it spent. */
export interface BudgetAllowance {
  max_calls: number
  used: number
  remaining: number
  /** The reasons a call was refused, in the order they happened. */
  overruns: string[]
}

/**
 * What a job's AI allowance was, and what it spent.
 *
 * The three allowances are reported separately because they are spent
 * for different reasons: a plan call and its repair happen once, while
 * the music calls happen once per clip.
 */
export interface JobBudget {
  job_id: string
  plan: BudgetAllowance
  repair: BudgetAllowance
  music: BudgetAllowance
  total_limit: number
  total_used: number
  remaining: number
  /** The refusals, each with the allowance it belongs to. */
  overruns: { category: string; reason: string }[]
  user_approved_overrides: boolean
  updated_at: string
  /** "not started" when the job has never run. */
  state?: string
}

/** What the plan says about one clip. */
export interface PlanDirection {
  clip_id: string
  layout: string
  crop: string
  caption_strategy: string
  music_track_id: string
  ducking_db: number
  transition: string
  reason: string
}

/**
 * The creative plan for a job.
 *
 * `source` is "ai" when the model's answer validated and "fallback"
 * when the deterministic plan was used instead. The fallback and the
 * problems are part of the answer: a plan that silently fell back would
 * read exactly like a plan the model agreed with.
 */
export interface JobPlan {
  job_id: string
  source: string
  clips: PlanDirection[]
  export_ratio: string
  export_settings: Record<string, unknown>
  notes: string[]
  problems: string[]
  music_verified: boolean
  /** "not planned yet" when the job has no plan. */
  state?: string
}

// -- Webcam layouts (M2) ------------------------------------------------------

/**
 * How the webcam and the gameplay sit together.
 *
 * `gameplay_only` never shows a webcam. `above` puts it in a strip over
 * the gameplay. `corner` draws it over the gameplay in one corner.
 */
export type LayoutVariant = 'gameplay_only' | 'above' | 'corner'

/** The corners the webcam can sit in. */
export type LayoutPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'

/**
 * What is known about one source's layout.
 *
 * The detected rectangle is where the detector found a face that held
 * still across cuts. The confidence is how sure it is. Nothing here
 * identifies anybody.
 */
export interface SourceLayout {
  source_id: string
  detected: boolean
  detected_x: number
  detected_y: number
  detected_width: number
  detected_height: number
  detected_confidence: number
  detected_face_width: number
  detected_reason: string
  detected_at: string
  /** The user's own choice. Empty means the automatic planner decides. */
  variant: string
  rect_x: number
  rect_y: number
  rect_width: number
  rect_height: number
  position: string
  scale: number
  updated_at: string
}

/** What one detection run found. */
export interface LayoutDetection {
  source_id: string
  found: boolean
  confidence: number
  rect: Record<string, number>
  reason: string
  sample_fps: number
  sampling_reason: string
  shots: number
  cuts_per_minute: number
  observations: number
}

/** One layout option, with the words that explain it. */
export interface LayoutVariantInfo {
  value: LayoutVariant
  title: string
  description: string
}

export interface LayoutOptions {
  variants: LayoutVariantInfo[]
  positions: LayoutPosition[]
}

// -- External processing (M0.5) -----------------------------------------------

/** One stored answer to "may this operation reach this class of host?". */
export interface ConsentDecision {
  destination_class: string
  granted: boolean
  source: string
  decided_at: string
  note: string
}

/** One external operation, with the user's decision for each destination class. */
export interface PrivacyOperation {
  operation: string
  title: string
  data: string
  why: string
  decisions: ConsentDecision[]
}

/** One recorded outbound transfer. Never contains the content itself. */
export interface TransferRecord {
  occurred_at: string
  operation: string
  provider: string
  destination: string
  destination_class: string
  data_summary: string
  outcome: string
  detail: string
  duration_ms: number
}

export interface Batch {
  id: string
  name: string
  status: 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'cancelled'
  settings: Record<string, unknown>
  created_at: string
  updated_at: string
  items?: BatchItem[]
  progress?: BatchProgress
}

// -- Trending research (Phase 12) --------------------------------------------

export interface TrendingVideo {
  video_id: string
  title: string
  channel: string
  published_at: string
  view_count: number
  category_id: string
  tags: string[]
  url: string
}

export interface TrendTheme {
  theme: string
  why: string
  fit: string
}

export interface TrendResearch {
  videos: TrendingVideo[]
  themes: TrendTheme[]
  formats: string[]
  avoid: string[]
  provider: string
  fetched_at: number
  from_cache: boolean
  error: string
  niche: string
  category_id: string
  region: string
}

export interface Notification {
  id: string
  kind: string
  severity: 'info' | 'success' | 'warning' | 'error'
  title: string
  body: string
  link: string
  entity_id: string
  read: boolean
  created_at: string
}

// -- AI providers (Phase 3, surfaced in Phase 17) ----------------------------

/**
 * One provider preset with the state of its key pool.
 *
 * `keys_healthy` is the number of keys that are enabled and not cooling down
 * — the ones that could actually answer a request right now.
 */
export interface ProviderPreset {
  key: string
  label: string
  adapter: string
  requires_key: boolean
  default_model: string
  default_base_url: string | null
  suggested_models: string[]
  capabilities: string[]
  is_local: boolean
  keys_total: number
  keys_healthy: number
  active: boolean
}

/** One key in a provider's pool. The value itself is never sent to the browser. */
export interface ProviderKey {
  label: string
  enabled: boolean
  failures: number
  last_error: string
  cooling_down: boolean
  last_used: string
}

// -- YouTube accounts and channels (Phase 10, surfaced in Phase 17) -----------

export interface YouTubeChannel {
  id: string
  account_id: string
  channel_id: string
  title: string
  url: string
  is_default: boolean
  privacy: string
  category_id: string
  auto_upload: boolean
  title_suffix: string
  /**
   * The audience declaration: '' (not decided), 'false' or 'true'.
   * An upload is refused while it is '' — it is a legal declaration,
   * not a setting AutoClip can choose for the owner.
   */
  made_for_kids: string
  created_at: string
  updated_at: string
}

export interface YouTubeAccount {
  id: string
  label: string
  email: string
  client_id: string
  connected_at: string
  created_at: string
  /** Whether a refresh token is stored. The token itself never leaves the server. */
  has_refresh_token: boolean
  /**
   * True when Google refused this account's credential and it has to be
   * connected again. Other accounts keep working.
   */
  needs_reconnect: boolean
  /** Why the connection broke, in plain words. */
  last_error: string
  channels: YouTubeChannel[]
}

// -- Routing (Phase 5, surfaced in Phase 17) ---------------------------------

export interface RoutingRule {
  id: string
  name: string
  match_keyword: string
  /** The channel *row* id (youtube_channels.id), not the YouTube channel id. */
  target_channel_id: string
  priority: number
  enabled: boolean
  extra_channel_ids: string[]
  created_at: string
  updated_at: string
}

export interface ClipClassification {
  clip_id: string
  category: string
  confidence: number
  provider: string
  reason: string
  created_at: string
}

// -- Restart history (Phase 17) ---------------------------------------------

/**
 * One restart of AutoClip and what it had to recover.
 *
 * The counts are the real numbers of rows that were recovered — not an
 * estimate of how much work was lost.
 */
export interface AppRestart {
  id: string
  started_at: string
  jobs_resumed: number
  uploads_resumed: number
  batch_items_resumed: number
  total_resumed: number
  job_ids: string[]
  upload_ids: string[]
  details: string
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  system: () => request<SystemStatus>('/api/system'),
  fetchModels: () => request<void>('/api/system/models', { method: 'POST' }),

  listSources: () => request<Source[]>('/api/sources'),

  ingestYouTube: (url: string, cookiesFromBrowser?: string) =>
    request<Source>('/api/sources/youtube', {
      method: 'POST',
      body: JSON.stringify({ url, cookies_from_browser: cookiesFromBrowser || null }),
    }),

  uploadSource: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Source>('/api/sources/upload', { method: 'POST', body: form })
  },

  listJobs: (limit = 25) => request<Job[]>(`/api/jobs?limit=${limit}`),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  createJob: (sourceId: string, settings: JobSettingsOverrides = {}) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, settings }),
    }),

  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),

  listClips: (jobId: string) => request<Clip[]>(`/api/jobs/${jobId}/clips`),
  listAllClips: (limit = 200) => request<LibraryClip[]>(`/api/clips?limit=${limit}`),
  getClip: (clipId: string) => request<Clip>(`/api/clips/${clipId}`),

  getCropPath: (clipId: string) => request<CropPath>(`/api/clips/${clipId}/crop-path`),
  getClipWords: (clipId: string) => request<Word[]>(`/api/clips/${clipId}/words`),

  patchClip: (
    clipId: string,
    patch: { start_s?: number; end_s?: number; title?: string; status?: ClipStatus },
  ) => request<Clip>(`/api/clips/${clipId}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  patchCaptions: (
    clipId: string,
    patch: { words?: Word[]; caption_style?: string; ratio?: string },
  ) =>
    request<Clip>(`/api/clips/${clipId}/captions`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  exportClip: (clipId: string, ratio: string, style: string, writeSrt = false) =>
    request<ExportRecord>(`/api/clips/${clipId}/export`, {
      method: 'POST',
      body: JSON.stringify({ ratio, style, write_srt: writeSrt }),
    }),

  captionStyles: () => request<CaptionStyle[]>('/api/caption-styles'),
  providerStatus: () => request<ProviderStatus[]>('/api/providers/status'),

  youtubeStatus: () => request<YouTubeStatus>('/api/youtube/status'),
  youtubeConnect: (accountId = '', label = '') =>
    request<{ auth_url: string }>('/api/youtube/connect', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, label }),
    }),
  youtubeDisconnect: (accountId = '') =>
    request<YouTubeStatus>('/api/youtube/disconnect', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId }),
    }),
  setYouTubeAuto: (enabled: boolean) =>
    request<YouTubeStatus>('/api/youtube/auto-upload', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
  setYouTubePrivacy: (privacy: 'private' | 'unlisted' | 'public') =>
    request<YouTubeStatus>('/api/youtube/privacy', {
      method: 'POST',
      body: JSON.stringify({ privacy }),
    }),
  retryUpload: (uploadId: string) =>
    request<UploadRecord>(`/api/youtube/uploads/${uploadId}/retry`, { method: 'POST' }),
  /** One upload, with the policy it was — and is — publishing under. */
  getUpload: (uploadId: string) => request<UploadRecord>(`/api/youtube/uploads/${uploadId}`),
  /**
   * Record an upload the owner says is on YouTube. The server checks
   * with YouTube before it records it.
   */
  confirmUpload: (uploadId: string, videoId: string) =>
    request<UploadRecord>(`/api/youtube/uploads/${uploadId}/confirm`, {
      method: 'PUT',
      body: JSON.stringify({ video_id: videoId }),
    }),
  /** Change what a queued upload will say and how it will be seen. */
  editUpload: (
    uploadId: string,
    patch: {
      title?: string
      description?: string
      tags?: string[]
      privacy?: 'private' | 'unlisted' | 'public'
      made_for_kids?: '' | 'false' | 'true'
    },
  ) =>
    request<UploadRecord>(`/api/youtube/uploads/${uploadId}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
  /** What the publishing policy would do for a destination. */
  youtubePolicy: (channelRowId = '') =>
    request<YouTubePolicy>(`/api/youtube/policy?channel_row_id=${encodeURIComponent(channelRowId)}`),
  /** How much of YouTube's daily API quota is left. */
  youtubeQuota: () => request<YouTubeQuota>('/api/youtube/quota'),
  /** Record the audience declaration for the global setting. */
  setYouTubeAudience: (madeForKids: '' | 'false' | 'true') =>
    request<YouTubeStatus>('/api/youtube/audience', {
      method: 'POST',
      body: JSON.stringify({ made_for_kids: madeForKids }),
    }),

  getSettings: () => request<Settings>('/api/settings'),
  putSettings: (patch: Partial<Settings>) =>
    request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),

  putSecret: (key: string, value: string) =>
    request<void>('/api/settings/secrets', {
      method: 'PUT',
      body: JSON.stringify({ key, value }),
    }),

  deleteSecret: (key: string) =>
    request<void>(`/api/settings/secrets/${key}`, { method: 'DELETE' }),

  mediaUrl: (jobId: string) => `/api/jobs/${jobId}/media`,

  // -- Workflows (Phase 7 visual builder) -----------------------------------
  workflowNodes: () => request<WorkflowNodeSpec[]>(`/api/workflows/nodes`),
  listWorkflows: () => request<Workflow[]>(`/api/workflows`),
  createWorkflow: (name: string, definition: WorkflowDefinition, description = '') =>
    request<Workflow>(`/api/workflows`, {
      method: 'POST',
      body: JSON.stringify({ name, description, definition }),
    }),
  getWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  saveWorkflow: (id: string, definition: WorkflowDefinition, name?: string) =>
    request<Workflow>(`/api/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ definition, name: name ?? null }),
    }),
  deleteWorkflow: (id: string) => request<void>(`/api/workflows/${id}`, { method: 'DELETE' }),
  runWorkflow: (id: string, jobId?: string) =>
    request<WorkflowRunResult>(`/api/workflows/${id}/run`, {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId ?? null }),
    }),
  workflowRuns: (workflowId?: string, limit = 50) =>
    request<WorkflowRun[]>(
      `/api/workflows/runs?${workflowId ? `workflow_id=${workflowId}&` : ''}limit=${limit}`,
    ),
  workflowRunDetail: (runId: string) => request<WorkflowRun>(`/api/workflows/runs/${runId}`),

  // -- Batches --------------------------------------------------------------
  listBatches: (limit = 50) => request<Batch[]>(`/api/batches?limit=${limit}`),
  createBatch: (name: string, settings: Record<string, unknown> = {}) =>
    request<Batch>(`/api/batches`, { method: 'POST', body: JSON.stringify({ name, settings }) }),
  getBatch: (id: string) => request<Batch>(`/api/batches/${id}`),
  deleteBatch: (id: string) => request<void>(`/api/batches/${id}`, { method: 'DELETE' }),
  addBatchSources: (id: string, sourceIds: string[]) =>
    request<{ added: number }>(`/api/batches/${id}/sources`, {
      method: 'POST',
      body: JSON.stringify({ source_ids: sourceIds }),
    }),
  launchBatch: (id: string) => request<Batch>(`/api/batches/${id}/launch`, { method: 'POST' }),
  pauseBatch: (id: string) => request<Batch>(`/api/batches/${id}/pause`, { method: 'POST' }),
  cancelBatch: (id: string) => request<Batch>(`/api/batches/${id}/cancel`, { method: 'POST' }),
  retryBatchFailed: (id: string) =>
    request<{ requeued: number }>(`/api/batches/${id}/retry-failed`, { method: 'POST' }),

  // -- Clip validation (Phase 9) --------------------------------------------
  validateClip: (clipId: string) =>
    request<{
      clip_id: string
      export_id: string
      ok: boolean
      checks: { name: string; ok: boolean; detail: string }[]
    }>(`/api/clips/${clipId}/validate`, { method: 'POST' }),

  // -- Music library (Phase 8) ----------------------------------------------
  listMusicTracks: () => request<MusicTrack[]>(`/api/music/tracks`),
  uploadMusicTrack: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<MusicTrack>(`/api/music/tracks`, { method: 'POST', body })
  },
  deleteMusicTrack: (name: string) =>
    request<void>(`/api/music/tracks/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // -- Music library (M1) ----------------------------------------------------
  listMusicLibrary: (filters: MusicFilters = {}) => {
    const query = new URLSearchParams()
    if (filters.q) query.set('q', filters.q)
    if (filters.mood) query.set('mood', filters.mood)
    if (filters.min_bpm !== undefined) query.set('min_bpm', String(filters.min_bpm))
    if (filters.max_bpm !== undefined) query.set('max_bpm', String(filters.max_bpm))
    if (filters.min_energy !== undefined) query.set('min_energy', String(filters.min_energy))
    if (filters.max_energy !== undefined) query.set('max_energy', String(filters.max_energy))
    if (filters.format) query.set('format', filters.format)
    if (filters.licence) query.set('licence', filters.licence)
    if (filters.favourite) query.set('favourite', 'true')
    if (filters.tag) query.set('tag', filters.tag)
    const suffix = query.toString()
    return request<MusicLibraryTrack[]>(`/api/music/library${suffix ? `?${suffix}` : ''}`)
  },
  listMusicFolders: () => request<MusicFolder[]>('/api/music/folders'),
  addMusicFolder: (path: string) =>
    request<{ folder: MusicFolder; scan: MusicScanReport }>('/api/music/folders', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  removeMusicFolder: (id: string) =>
    request<void>(`/api/music/folders/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  scanMusicLibrary: () => request<MusicScanReport>('/api/music/scan', { method: 'POST' }),
  removeMusicLibraryTrack: (id: string) =>
    request<void>(`/api/music/library/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  setMusicFlags: (
    id: string,
    flags: { favourite?: boolean; excluded?: boolean; tags?: string; title?: string; artist?: string },
  ) =>
    request<MusicLibraryTrack>(`/api/music/library/${encodeURIComponent(id)}/flags`, {
      method: 'POST',
      body: JSON.stringify(flags),
    }),
  analyseMusicTrack: (id: string, force = false) =>
    request<MusicLibraryTrack>(
      `/api/music/library/${encodeURIComponent(id)}/analyse?force=${force}`,
      { method: 'POST' },
    ),
  getMusicLicence: (id: string) =>
    request<MusicLicense>(`/api/music/library/${encodeURIComponent(id)}/licence`),
  putMusicLicence: (
    id: string,
    licence: {
      state: LicenseState
      source?: string
      evidence?: string
      attribution?: string
      commercial_use?: boolean
      non_commercial?: boolean
      derivative?: boolean
      share_alike?: boolean
      expires_at?: string
    },
  ) =>
    request<MusicLicense>(`/api/music/library/${encodeURIComponent(id)}/licence`, {
      method: 'PUT',
      body: JSON.stringify(licence),
    }),
  musicPreviewUrl: (id: string) => `/api/music/library/${encodeURIComponent(id)}/audio`,
  musicEnvelope: (jobId: string, startS = 0, endS = 0) =>
    request<MusicEnvelope>(
      `/api/music/envelope?job_id=${encodeURIComponent(jobId)}&start_s=${startS}&end_s=${endS}`,
    ),

  // -- Creative intelligence (M3) ---------------------------------------------

  /** The shapes a track can be filtered by, with the measurement behind each. */
  musicFormats: () => request<MusicFormat[]>('/api/music/formats'),

  /** The music choice that applies, and where it came from. */
  musicPreferences: (clipId = '', sourceId = '') => {
    const query = new URLSearchParams()
    if (clipId) query.set('clip_id', clipId)
    if (sourceId) query.set('source_id', sourceId)
    const suffix = query.toString()
    return request<MusicPreferences>(`/api/music/preferences${suffix ? `?${suffix}` : ''}`)
  },

  /**
   * Record the music choice at one scope.
   *
   * An empty track id clears the scope. The sentinel `__none__` means
   * "no music at all", which is a different answer from "no preference
   * here".
   */
  putMusicPreference: (
    scope: 'global' | 'source' | 'clip',
    scopeId: string,
    trackId: string,
  ) =>
    request<MusicPreference>('/api/music/preferences', {
      method: 'PUT',
      body: JSON.stringify({ scope, scope_id: scopeId, track_id: trackId }),
    }),

  /** Forget one scope's preference. The other scopes are untouched. */
  clearMusicPreference: (scope: 'global' | 'source' | 'clip', scopeId = '') => {
    const query = new URLSearchParams({ scope })
    if (scopeId) query.set('scope_id', scopeId)
    return request<MusicPreference>(`/api/music/preferences?${query.toString()}`, {
      method: 'DELETE',
    })
  },

  /** What a job's AI allowance was, and what it spent. */
  jobBudget: (jobId: string) => request<JobBudget>(`/api/jobs/${encodeURIComponent(jobId)}/budget`),

  /** The creative plan for a job, and why any of it was rejected. */
  jobPlan: (jobId: string) => request<JobPlan>(`/api/jobs/${encodeURIComponent(jobId)}/plan`),

  /** The objective quality measurements for a clip. */
  clipDiagnostics: (clipId: string) =>
    request<ClipDiagnostics>(`/api/clips/${encodeURIComponent(clipId)}/diagnostics`),

  // -- External processing (M0.5) ---------------------------------------------
  listConsents: () => request<PrivacyOperation[]>('/api/privacy/consents'),
  putConsent: (operation: string, destinationClass: string, granted: boolean) =>
    request<PrivacyOperation[]>('/api/privacy/consents', {
      method: 'PUT',
      body: JSON.stringify({
        operation,
        destination_class: destinationClass,
        granted,
      }),
    }),
  listTransfers: (limit = 50) =>
    request<TransferRecord[]>(`/api/privacy/transfers?limit=${limit}`),

  // -- Webcam layouts (M2) ----------------------------------------------------
  listLayouts: () => request<SourceLayout[]>('/api/layout/sources'),
  getLayout: (sourceId: string) =>
    request<SourceLayout>(`/api/layout/sources/${encodeURIComponent(sourceId)}`),
  putLayout: (
    sourceId: string,
    layout: {
      variant: string
      rect_x?: number
      rect_y?: number
      rect_width?: number
      rect_height?: number
      position?: string
      scale?: number
    },
  ) =>
    request<SourceLayout>(`/api/layout/sources/${encodeURIComponent(sourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ source_id: sourceId, ...layout }),
    }),
  clearLayout: (sourceId: string) =>
    request<SourceLayout>(`/api/layout/sources/${encodeURIComponent(sourceId)}`, {
      method: 'DELETE',
    }),
  detectLayout: (sourceId: string) =>
    request<LayoutDetection>(
      `/api/layout/sources/${encodeURIComponent(sourceId)}/detect`,
      { method: 'POST' },
    ),
  layoutOptions: () => request<LayoutOptions>('/api/layout/variants'),

  // -- Learning (Phase 11) ---------------------------------------------------
  learningSummary: () =>
    request<{
      clips: number
      exported: number
      invalid: number
      discarded: number
      uploads_done: number
      uploads_failed: number
      sources: number
      validation_failures: Record<string, number>
    }>('/api/learning/summary'),
  learningScoreBands: () =>
    request<
      {
        band: string
        total: number
        kept: number
        discarded: number
        exported: number
        uploaded: number
        trimmed: number
        keep_rate: number
        export_rate: number
      }[]
    >('/api/learning/score-bands'),
  learningChannels: () =>
    request<
      {
        channel_row_id: string
        channel_title: string
        total: number
        done: number
        failed: number
        skipped: number
        pending: number
      }[]
    >('/api/learning/channels'),
  learningFeedback: () =>
    request<{ path: string; content: string; max_chars: number }>('/api/learning/feedback'),
  saveLearningFeedback: (content: string) =>
    request<{ saved: boolean; active_chars: number }>('/api/learning/feedback', {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  channelNote: (channelId: string) =>
    request<{ channel_id: string; note: string; path: string }>(
      `/api/learning/channel-note/${encodeURIComponent(channelId)}`,
    ),
  saveChannelNote: (channelId: string, note: string) =>
    request<{ saved: boolean; note: string }>(
      `/api/learning/channel-note/${encodeURIComponent(channelId)}`,
      { method: 'PUT', body: JSON.stringify({ channel_id: channelId, note }) },
    ),

  // -- Trending research (Phase 12) -----------------------------------------
  currentTrends: (niche = '', categoryId = '', region = 'US') => {
    const params = new URLSearchParams()
    if (niche) params.set('niche', niche)
    if (categoryId) params.set('category_id', categoryId)
    if (region) params.set('region', region)
    const query = params.toString()
    return request<TrendResearch>(`/api/trends/current${query ? `?${query}` : ''}`)
  },
  refreshTrends: (payload: {
    niche?: string
    category_id?: string
    region?: string
    force?: boolean
  }) =>
    request<TrendResearch>('/api/trends/refresh', {
      method: 'POST',
      body: JSON.stringify({ force: true, ...payload }),
    }),
  trendContext: () =>
    request<{
      available: boolean
      section: string
      video_count: number
      fetched_at: number
      provider: string
    }>('/api/trends/context'),

  // -- Project-aware assistant (Phase 13) -----------------------------------
  chatStarters: () => request<{ starters: string[] }>('/api/chat/starters'),
  chatContext: (clipId = '', jobId = '') => {
    const params = new URLSearchParams()
    if (clipId) params.set('clip_id', clipId)
    if (jobId) params.set('job_id', jobId)
    const query = params.toString()
    return request<{ context: Record<string, unknown>; prompt: string }>(
      `/api/chat/context${query ? `?${query}` : ''}`,
    )
  },
  askAssistant: (message: string, history: { role: string; content: string }[] = []) =>
    request<{ answer: string; provider: string; context: Record<string, unknown> }>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
    }),

  // -- Notification centre (Phase 14) ---------------------------------------
  listNotifications: (limit = 50, unreadOnly = false) =>
    request<Notification[]>(
      `/api/notifications?limit=${limit}${unreadOnly ? '&unread_only=true' : ''}`,
    ),
  unreadNotificationCount: () => request<{ unread: number }>('/api/notifications/unread-count'),
  markNotificationRead: (id: string) =>
    request<{ read: boolean }>(`/api/notifications/${encodeURIComponent(id)}/read`, {
      method: 'POST',
    }),
  markAllNotificationsRead: () =>
    request<{ marked: number }>('/api/notifications/read-all', { method: 'POST' }),
  deleteNotification: (id: string) =>
    request<{ deleted: boolean }>(`/api/notifications/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  clearReadNotifications: () =>
    request<{ removed: number }>('/api/notifications/clear', { method: 'POST' }),

  // -- Recovery centre (Phase 15) ------------------------------------------
  recoveryReport: () =>
    request<{
      items: {
        kind: 'job' | 'upload' | 'clip'
        id: string
        title: string
        detail: string
        code: string
        retryable: boolean
        action: string
        action_label: string
        link: string
        entity_id: string
        created_at: string
      }[]
      counts: { job: number; upload: number; clip: number; total: number }
    }>('/api/recovery'),
  /**
   * Run a recovery action.
   *
   * A re-render action needs an export body; the retry endpoints take none.
   * The action path says which it is, so the caller does not have to know.
   */
  retryAction: (action: string) =>
    request<unknown>(action, {
      method: 'POST',
      body: action.includes('/export')
        ? JSON.stringify({ ratio: '9:16', style: 'bold_pop', write_srt: false })
        : undefined,
    }),

  // -- Resource usage and cleanup (Phase 16) --------------------------------
  resources: () => request<ResourceOverview>('/api/resources'),
  cleanupResources: () =>
    request<CleanupReport>('/api/resources/cleanup', { method: 'POST' }),

  // -- AI providers (Phase 3, surfaced in Phase 17) -------------------------
  listProviders: () => request<ProviderPreset[]>('/api/ai/providers'),
  providerPresets: () => request<Record<string, Omit<ProviderPreset, 'key' | 'requires_key' | 'keys_total' | 'keys_healthy' | 'active'>>>('/api/ai/presets'),
  providerKeys: (key: string) =>
    request<ProviderKey[]>(`/api/ai/providers/${encodeURIComponent(key)}/keys`),
  addProviderKey: (key: string, label: string, value: string) =>
    request<{ stored: string }>(`/api/ai/providers/${encodeURIComponent(key)}/keys`, {
      method: 'POST',
      body: JSON.stringify({ label, value }),
    }),
  removeProviderKey: (key: string, label: string) =>
    request<void>(
      `/api/ai/providers/${encodeURIComponent(key)}/keys/${encodeURIComponent(label)}`,
      { method: 'DELETE' },
    ),
  setProviderKeyEnabled: (key: string, label: string, enabled: boolean) =>
    request<void>(
      `/api/ai/providers/${encodeURIComponent(key)}/keys/${encodeURIComponent(label)}/state`,
      { method: 'PUT', body: JSON.stringify({ enabled }) },
    ),

  // -- YouTube accounts and channels (Phase 10, surfaced in Phase 17) --------
  listYouTubeAccounts: () => request<YouTubeAccount[]>('/api/youtube/accounts'),
  createYouTubeAccount: (label: string, email: string) =>
    request<YouTubeAccount>('/api/youtube/accounts', {
      method: 'POST',
      body: JSON.stringify({ label, email }),
    }),
  /** Start a sign-in for one account. The token comes back filed under it. */
  connectYouTubeAccount: (accountId: string) =>
    request<{ auth_url: string }>(`/api/youtube/accounts/${encodeURIComponent(accountId)}/connect`, {
      method: 'POST',
    }),
  /** Disconnect one account. The other accounts are left alone. */
  disconnectYouTubeAccount: (accountId: string) =>
    request<{ disconnected: boolean }>(
      `/api/youtube/accounts/${encodeURIComponent(accountId)}/disconnect`,
      { method: 'POST' },
    ),
  deleteYouTubeAccount: (id: string) =>
    request<void>(`/api/youtube/accounts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listYouTubeChannels: (accountId: string) =>
    request<YouTubeChannel[]>(`/api/youtube/accounts/${encodeURIComponent(accountId)}/channels`),
  addYouTubeChannel: (
    accountId: string,
    channel: {
      privacy?: string
      category_id?: string
      auto_upload?: boolean
      is_default?: boolean | null
      title_suffix?: string
    },
  ) =>
    request<YouTubeChannel>(`/api/youtube/accounts/${encodeURIComponent(accountId)}/channels`, {
      method: 'POST',
      body: JSON.stringify(channel),
    }),
  updateYouTubeChannel: (
    channelRowId: string,
    patch: {
      privacy?: string
      category_id?: string
      auto_upload?: boolean
      is_default?: boolean
      title?: string
      title_suffix?: string
    },
  ) =>
    request<YouTubeChannel>(`/api/youtube/accounts/channels/${encodeURIComponent(channelRowId)}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
  deleteYouTubeChannel: (channelRowId: string) =>
    request<void>(`/api/youtube/accounts/channels/${encodeURIComponent(channelRowId)}`, {
      method: 'DELETE',
    }),

  // -- Routing (Phase 5, surfaced in Phase 17) ------------------------------
  routingCategories: () => request<string[]>('/api/routing/categories'),
  listRoutingRules: () => request<RoutingRule[]>('/api/routing/rules'),
  createRoutingRule: (rule: {
    name?: string
    match_keyword: string
    target_channel_id: string
    priority?: number
    enabled?: boolean
    extra_channel_ids?: string[]
  }) =>
    request<RoutingRule>('/api/routing/rules', {
      method: 'POST',
      body: JSON.stringify(rule),
    }),
  updateRoutingRule: (
    ruleId: string,
    patch: {
      name?: string
      match_keyword?: string
      target_channel_id?: string
      priority?: number
      enabled?: boolean
      extra_channel_ids?: string[]
    },
  ) =>
    request<RoutingRule>(`/api/routing/rules/${encodeURIComponent(ruleId)}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
  deleteRoutingRule: (ruleId: string) =>
    request<void>(`/api/routing/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' }),
  clipClassification: (clipId: string) =>
    request<ClipClassification>(`/api/routing/clips/${encodeURIComponent(clipId)}/classification`),
  classifyClip: (clipId: string) =>
    request<ClipClassification>(`/api/routing/clips/${encodeURIComponent(clipId)}/classify`, {
      method: 'POST',
    }),
  clipTarget: (clipId: string) =>
    request<YouTubeChannel & { channel_row_id?: string }>(
      `/api/routing/clips/${encodeURIComponent(clipId)}/target`,
    ),
  /**
   * Where this clip would go right now, and why: the category, the
   * channel, the reason, the rule, the confidence and whether it was a
   * fallback.
   */
  clipRouting: (clipId: string) =>
    request<RoutingDecision>(`/api/routing/clips/${encodeURIComponent(clipId)}/decision`),
  /** The routing decisions that have already been made, newest first. */
  routingDecisions: (limit = 20) =>
    request<RoutingDecision[]>(`/api/routing/decisions?limit=${limit}`),

  // -- Restart history (Phase 17) ------------------------------------------
  listRestarts: (limit = 20) =>
    request<{
      restarts: AppRestart[]
      latest: AppRestart | null
      count: number
      restarts_with_work: number
    }>(`/api/restarts?limit=${limit}`),
}

/** Format seconds as m:ss, or h:mm:ss past an hour. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const s = total % 60
  const m = Math.floor(total / 60) % 60
  const h = Math.floor(total / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** Format seconds as timecode with centiseconds, for trim handles. */
export function formatTimecode(seconds: number): string {
  const total = Math.max(0, seconds)
  const cs = Math.floor((total % 1) * 100)
  const s = Math.floor(total) % 60
  const m = Math.floor(total / 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(m)}:${pad(s)}.${pad(cs)}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}
