import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, ArrowRight, Check, ClipboardList, FileText, Loader2, Save, Sparkles,
} from 'lucide-react'
import Card, { CardBody, CardHeader } from '../components/Card'
import * as api from '../api'

const STORAGE_PREFIX = 'tron-plan-wizard:'

const COMPLIANCE_OPTIONS = [
  { id: 'soc2', label: 'SOC 2' },
  { id: 'iso27001', label: 'ISO 27001' },
  { id: 'hipaa', label: 'HIPAA' },
  { id: 'pci', label: 'PCI-DSS' },
  { id: 'gdpr', label: 'GDPR / privacy' },
] as const

export type PlanQuestionnaireForm = {
  product_summary: string
  primary_users: string
  success_metrics: string
  tech_stack: string
  deployment_model: string
  scale_expectations: string
  compliance_frameworks: string[]
  data_classes: string
  integrations: string
  non_functional: string
  timeline: string
  risks_assumptions: string
  open_questions: string
}

const emptyForm = (): PlanQuestionnaireForm => ({
  product_summary: '',
  primary_users: '',
  success_metrics: '',
  tech_stack: '',
  deployment_model: '',
  scale_expectations: '',
  compliance_frameworks: [],
  data_classes: '',
  integrations: '',
  non_functional: '',
  timeline: '',
  risks_assumptions: '',
  open_questions: '',
})

const STEPS = [
  { id: 0, title: 'Product & outcomes', desc: 'What you are building and why it matters' },
  { id: 1, title: 'Engineering context', desc: 'Stack, deployment, and scale' },
  { id: 2, title: 'Compliance & data', desc: 'Frameworks and sensitive data' },
  { id: 3, title: 'Delivery', desc: 'Integrations, NFRs, timeline, risks' },
  { id: 4, title: 'Review & generate', desc: 'Preview and run PLAN workflow' },
] as const

function formFromServer(q: unknown): PlanQuestionnaireForm {
  const base = emptyForm()
  if (!q || typeof q !== 'object') return base
  const o = q as Record<string, unknown>
  const pick = (k: keyof PlanQuestionnaireForm): string =>
    typeof o[k] === 'string' ? o[k] as string : ''
  const cf = o.compliance_frameworks
  const frameworks = Array.isArray(cf)
    ? cf.map(String).filter(Boolean)
    : typeof cf === 'string' && cf
      ? cf.split(',').map(s => s.trim()).filter(Boolean)
      : []
  return {
    ...base,
    product_summary: pick('product_summary'),
    primary_users: pick('primary_users'),
    success_metrics: pick('success_metrics'),
    tech_stack: pick('tech_stack'),
    deployment_model: pick('deployment_model'),
    scale_expectations: pick('scale_expectations'),
    compliance_frameworks: frameworks,
    data_classes: pick('data_classes'),
    integrations: pick('integrations'),
    non_functional: pick('non_functional'),
    timeline: pick('timeline'),
    risks_assumptions: pick('risks_assumptions'),
    open_questions: pick('open_questions'),
  }
}

function toQuestionnairePayload(f: PlanQuestionnaireForm): Record<string, unknown> {
  return {
    product_summary: f.product_summary.trim(),
    primary_users: f.primary_users.trim(),
    success_metrics: f.success_metrics.trim(),
    tech_stack: f.tech_stack.trim(),
    deployment_model: f.deployment_model.trim(),
    scale_expectations: f.scale_expectations.trim(),
    compliance_frameworks: f.compliance_frameworks,
    data_classes: f.data_classes.trim(),
    integrations: f.integrations.trim(),
    non_functional: f.non_functional.trim(),
    timeline: f.timeline.trim(),
    risks_assumptions: f.risks_assumptions.trim(),
    open_questions: f.open_questions.trim(),
  }
}

export default function PlanWizard() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<api.ProjectDetail | null>(null)
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<PlanQuestionnaireForm>(emptyForm)
  const [goalsOverride, setGoalsOverride] = useState('')
  const [constraintsOverride, setConstraintsOverride] = useState('')
  const [writeTron, setWriteTron] = useState(true)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSaved, setLastSaved] = useState<Date | null>(null)
  /** Avoid PUT-ing an empty form on first mount (would wipe server draft). */
  const [dirty, setDirty] = useState(false)
  const touch = useCallback(() => setDirty(true), [])

  useEffect(() => {
    if (!id) return
    let cancelled = false
    ;(async () => {
      try {
        const p = await api.getProject(id)
        if (cancelled) return
        setProject(p)
        const localRaw = localStorage.getItem(STORAGE_PREFIX + id)
        if (localRaw) {
          try {
            const parsed = JSON.parse(localRaw) as { form?: PlanQuestionnaireForm }
            if (parsed.form) {
              setForm({ ...emptyForm(), ...parsed.form })
              setDirty(true)
              return
            }
          } catch { /* ignore */ }
        }
        if (p.plan_questionnaire_json) {
          setForm(formFromServer(p.plan_questionnaire_json))
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load project')
      }
    })()
    return () => { cancelled = true }
  }, [id])

  useEffect(() => {
    if (!id) return
    const t = window.setTimeout(() => {
      localStorage.setItem(
        STORAGE_PREFIX + id,
        JSON.stringify({ form, step, updatedAt: Date.now() }),
      )
    }, 400)
    return () => clearTimeout(t)
  }, [id, form, step])

  const debouncedServerSave = useMemo(() => {
    let timer: number
    return (payload: Record<string, unknown>) => {
      if (!id) return
      window.clearTimeout(timer)
      timer = window.setTimeout(async () => {
        setSaving(true)
        setError(null)
        try {
          await api.updateProject(id, { plan_questionnaire_json: payload })
          setLastSaved(new Date())
        } catch (e) {
          setError(e instanceof Error ? e.message : 'Draft save failed')
        } finally {
          setSaving(false)
        }
      }, 900)
    }
  }, [id])

  useEffect(() => {
    if (!id || !project || !dirty) return
    debouncedServerSave(toQuestionnairePayload(form))
  }, [id, project, form, dirty, debouncedServerSave])

  const toggleCompliance = (cid: string) => {
    touch()
    setForm(f => {
      const has = f.compliance_frameworks.includes(cid)
      return {
        ...f,
        compliance_frameworks: has
          ? f.compliance_frameworks.filter(x => x !== cid)
          : [...f.compliance_frameworks, cid],
      }
    })
  }

  const canProceed = useCallback(() => {
    if (step === 0) return form.product_summary.trim().length >= 3
    return true
  }, [step, form.product_summary])

  const compiledPreview = useMemo(() => {
    const q = toQuestionnairePayload(form)
    const goals =
      goalsOverride.trim() ||
      [
        q.product_summary && `Product: ${q.product_summary}`,
        q.primary_users && `Users: ${q.primary_users}`,
        q.success_metrics && `Success: ${q.success_metrics}`,
      ]
        .filter(Boolean)
        .join('\n\n')
    const constraints =
      constraintsOverride.trim() ||
      [
        q.tech_stack && `Tech: ${q.tech_stack}`,
        q.deployment_model && `Deploy: ${q.deployment_model}`,
        q.scale_expectations && `Scale: ${q.scale_expectations}`,
        Array.isArray(q.compliance_frameworks) && q.compliance_frameworks.length
          ? `Compliance: ${q.compliance_frameworks.join(', ')}`
          : '',
        q.data_classes && `Data: ${q.data_classes}`,
        q.integrations && `Integrations: ${q.integrations}`,
        q.non_functional && `NFR: ${q.non_functional}`,
        q.timeline && `Timeline: ${q.timeline}`,
        q.risks_assumptions && `Risks: ${q.risks_assumptions}`,
        q.open_questions && `Open questions: ${q.open_questions}`,
      ]
        .filter(Boolean)
        .join('\n\n')
    return { goals, constraints, q }
  }, [form, goalsOverride, constraintsOverride])

  async function handleGenerate() {
    if (!id) return
    setStarting(true)
    setError(null)
    try {
      const g = compiledPreview.goals.trim()
      const c = compiledPreview.constraints.trim()
      const qVals = Object.values(compiledPreview.q).some(v => {
        if (Array.isArray(v)) return v.length > 0
        return v != null && String(v).trim().length > 0
      })
      if (g.length < 3 && !qVals) {
        setError('Add a short product summary (step 1) or free-text goals.')
        return
      }
      await api.startPlanWorkflow(id, {
        goals: g.length >= 3 ? g : '',
        constraints: c,
        questionnaire: compiledPreview.q as api.PlanQuestionnairePayload,
        write_tron_files: writeTron,
      })
      navigate(`/projects/${id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Plan start failed'
      setError(msg)
    } finally {
      setStarting(false)
    }
  }

  if (!id) return null

  if (!project) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-tron-500">
        {error ?? 'Loading…'}
      </div>
    )
  }

  return (
    <div className="p-6 w-full space-y-6">
      <div className="flex items-center gap-4">
        <Link
          to={`/projects/${id}`}
          className="p-2 rounded-lg hover:bg-tron-700 text-tron-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <ClipboardList className="w-6 h-6 text-accent-light" />
            Interactive plan
          </h1>
          <p className="text-sm text-tron-400 mt-1">
            {project.name} — structured questionnaire (proposal PLAN mode)
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-tron-500">
          {saving ? (
            <><Loader2 className="w-3 h-3 animate-spin" /> Saving…</>
          ) : lastSaved ? (
            <><Save className="w-3 h-3" /> Draft saved</>
          ) : null}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
          {error.includes('503') || error.toLowerCase().includes('temporal') ? (
            <p className="mt-2 text-tron-400">
              PLAN runs on Temporal. Set <code className="text-tron-300">TEMPORAL_ENABLED=true</code> and ensure the worker is up.
            </p>
          ) : null}
        </div>
      )}

      {/* Step indicators */}
      <div className="flex flex-wrap gap-2">
        {STEPS.map(s => (
          <button
            key={s.id}
            type="button"
            onClick={() => setStep(s.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              step === s.id
                ? 'bg-accent text-white'
                : 'bg-tron-800 text-tron-400 hover:text-white border border-tron-700'
            }`}
          >
            {s.id + 1}. {s.title}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <span className="text-white font-medium">{STEPS[step].title}</span>
          <p className="text-xs text-tron-500 mt-1">{STEPS[step].desc}</p>
        </CardHeader>
        <CardBody className="space-y-4">
          {step === 0 && (
            <>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Product / outcome *</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[100px] focus:ring-1 focus:ring-accent focus:border-accent outline-none"
                  placeholder="What are you building? What problem does it solve?"
                  value={form.product_summary}
                                   onChange={e => { touch(); setForm(f => ({ ...f, product_summary: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Primary users</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="Personas, internal vs external, trust boundaries"
                  value={form.primary_users}
                  onChange={e => { touch(); setForm(f => ({ ...f, primary_users: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Success metrics</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="SLIs, adoption, revenue, defect rates…"
                  value={form.success_metrics}
                  onChange={e => { touch(); setForm(f => ({ ...f, success_metrics: e.target.value })) }}
                />
              </label>
            </>
          )}

          {step === 1 && (
            <>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Tech stack & preferences</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[88px]"
                  placeholder="Languages, frameworks, DBs, messaging…"
                  value={form.tech_stack}
                  onChange={e => { touch(); setForm(f => ({ ...f, tech_stack: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Deployment model</span>
                <input
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3"
                  placeholder="SaaS, single-tenant, on-prem, hybrid…"
                  value={form.deployment_model}
                  onChange={e => { touch(); setForm(f => ({ ...f, deployment_model: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Scale expectations</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="Traffic, data volume, multi-region, peak patterns…"
                  value={form.scale_expectations}
                  onChange={e => { touch(); setForm(f => ({ ...f, scale_expectations: e.target.value })) }}
                />
              </label>
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <span className="text-xs text-tron-400 uppercase tracking-wide">Compliance frameworks</span>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COMPLIANCE_OPTIONS.map(opt => {
                    const on = form.compliance_frameworks.includes(opt.id)
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => toggleCompliance(opt.id)}
                        className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                          on
                            ? 'bg-accent/20 border-accent text-accent-light'
                            : 'bg-tron-800 border-tron-600 text-tron-400 hover:border-tron-500'
                        }`}
                      >
                        {on && <Check className="w-3 h-3 inline mr-1 -mt-0.5" />}
                        {opt.label}
                      </button>
                    )
                  })}
                </div>
              </div>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Sensitive data classes</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="PII, PHI, payment data, secrets, audit logs…"
                  value={form.data_classes}
                  onChange={e => { touch(); setForm(f => ({ ...f, data_classes: e.target.value })) }}
                />
              </label>
            </>
          )}

          {step === 3 && (
            <>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Integrations</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="APIs, webhooks, IdPs, data warehouses…"
                  value={form.integrations}
                  onChange={e => { touch(); setForm(f => ({ ...f, integrations: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Non-functional requirements</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  placeholder="Latency, availability, RPO/RTO, accessibility…"
                  value={form.non_functional}
                  onChange={e => { touch(); setForm(f => ({ ...f, non_functional: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Timeline / milestones</span>
                <input
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3"
                  placeholder="MVP date, hard deadlines…"
                  value={form.timeline}
                  onChange={e => { touch(); setForm(f => ({ ...f, timeline: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Risks & assumptions</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[72px]"
                  value={form.risks_assumptions}
                  onChange={e => { touch(); setForm(f => ({ ...f, risks_assumptions: e.target.value })) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400 uppercase tracking-wide">Open questions</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[56px]"
                  value={form.open_questions}
                  onChange={e => { touch(); setForm(f => ({ ...f, open_questions: e.target.value })) }}
                />
              </label>
            </>
          )}

          {step === 4 && (
            <>
              <p className="text-sm text-tron-400">
                This preview is what the planner LLM receives (merged with any overrides below).
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <span className="text-xs text-tron-500">Compiled goals</span>
                  <pre className="mt-1 text-xs text-tron-300 bg-tron-950 border border-tron-700 rounded-lg p-3 max-h-48 overflow-auto whitespace-pre-wrap">
                    {compiledPreview.goals || '—'}
                  </pre>
                </div>
                <div>
                  <span className="text-xs text-tron-500">Compiled constraints</span>
                  <pre className="mt-1 text-xs text-tron-300 bg-tron-950 border border-tron-700 rounded-lg p-3 max-h-48 overflow-auto whitespace-pre-wrap">
                    {compiledPreview.constraints || '—'}
                  </pre>
                </div>
              </div>
              <label className="block">
                <span className="text-xs text-tron-400">Optional: override goals (prepended to questionnaire)</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[64px]"
                  value={goalsOverride}
                  onChange={e => { touch(); setGoalsOverride(e.target.value) }}
                />
              </label>
              <label className="block">
                <span className="text-xs text-tron-400">Optional: override constraints</span>
                <textarea
                  className="mt-1 w-full rounded-lg bg-tron-800 border border-tron-600 text-white text-sm p-3 min-h-[64px]"
                  value={constraintsOverride}
                  onChange={e => { touch(); setConstraintsOverride(e.target.value) }}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-tron-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={writeTron}
                  onChange={e => setWriteTron(e.target.checked)}
                  className="rounded border-tron-600"
                />
                Request <code className="text-xs text-accent-light">.tron/</code> bundle git push when{' '}
                <code className="text-xs">TRON_PLAN_GIT_TOKEN</code> is set on the worker
              </label>
            </>
          )}
        </CardBody>
      </Card>

      <div className="flex justify-between items-center">
        <button
          type="button"
          disabled={step <= 0}
          onClick={() => setStep(s => Math.max(0, s - 1))}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-tron-600 text-tron-300 hover:bg-tron-800 disabled:opacity-40 text-sm"
        >
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
        {step < STEPS.length - 1 ? (
          <button
            type="button"
            disabled={!canProceed()}
            onClick={() => setStep(s => Math.min(STEPS.length - 1, s + 1))}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent hover:bg-accent-dark text-white text-sm font-medium disabled:opacity-40"
          >
            Next <ArrowRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            type="button"
            disabled={starting}
            onClick={handleGenerate}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium disabled:opacity-50"
          >
            {starting ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Starting…</>
            ) : (
              <><Sparkles className="w-4 h-4" /> Generate plan (Temporal)</>
            )}
          </button>
        )}
      </div>

      <p className="text-xs text-tron-500 flex items-center gap-1">
        <FileText className="w-3 h-3" />
        Output is stored in <code className="text-tron-400">plan_artifact_json</code> and optional{' '}
        <code className="text-tron-400">.tron/</code> files in the repo.
      </p>
    </div>
  )
}
