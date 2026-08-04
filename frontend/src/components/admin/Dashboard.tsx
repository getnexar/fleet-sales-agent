import { useEffect } from 'react'
import { useAdminStats } from '../../hooks/useAdmin'
import type { AdminStats } from '../../types'

// ─── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, tone }: { label: string; value: number | string; sub?: string; tone?: 'primary' | 'danger' }) {
  const accentColor = tone === 'danger' ? '#991b1b' : tone === 'primary' ? 'var(--primary)' : undefined
  return (
    <div style={{
      background: 'var(--card)',
      border: `1px solid ${tone === 'danger' ? '#fca5a5' : tone === 'primary' ? 'var(--primary)' : 'var(--border)'}`,
      borderRadius: 12,
      padding: '20px 24px',
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 11, color: 'var(--muted-foreground)', fontWeight: 600, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
        {label}
      </div>
      <div style={{ fontSize: 36, fontWeight: 700, fontFamily: 'var(--font-heading)', color: accentColor ?? 'var(--foreground)', lineHeight: 1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginTop: 6 }}>{sub}</div>}
    </div>
  )
}

// ─── Monthly Bar Chart (vertical) ────────────────────────────────────────────

function MonthlyChart({ data }: { data: AdminStats['monthly_leads'] }) {
  const max = Math.max(...data.map(d => d.count), 1)
  const hasData = data.some(d => d.count > 0)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 80, marginBottom: 6 }}>
        {data.map(item => (
          <div key={item.month} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
            {item.count > 0 && (
              <div style={{ fontSize: 11, color: 'var(--foreground)', fontWeight: 600 }}>{item.count}</div>
            )}
            <div style={{
              width: '100%',
              height: `${Math.max((item.count / max) * 64, item.count > 0 ? 4 : 2)}px`,
              background: item.count > 0 ? 'var(--primary)' : 'var(--border)',
              borderRadius: '4px 4px 0 0',
              opacity: item.count > 0 ? 0.85 : 0.5,
            }} />
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {data.map(item => (
          <div key={item.month} style={{ flex: 1, fontSize: 10, color: 'var(--muted-foreground)', textAlign: 'center', lineHeight: 1.3 }}>
            {item.month.split(' ')[0]}
          </div>
        ))}
      </div>
      {!hasData && (
        <div style={{ textAlign: 'center', color: 'var(--muted-foreground)', fontSize: 12, marginTop: 8 }}>
          No data yet
        </div>
      )}
    </div>
  )
}

// ─── Horizontal Bar Chart ────────────────────────────────────────────────────

function HBarChart({ data, labelKey }: {
  data: { count: number; [key: string]: string | number }[]
  labelKey: string
}) {
  const max = Math.max(...data.map(d => d.count), 1)

  if (data.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--muted-foreground)', padding: '12px 0' }}>No data yet</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {data.map((item, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 90, fontSize: 12, color: 'var(--foreground)', flexShrink: 0, fontWeight: 500 }}>
            {String(item[labelKey])}
          </div>
          <div style={{ flex: 1, background: 'var(--muted)', borderRadius: 4, height: 18, position: 'relative', overflow: 'hidden' }}>
            <div style={{
              width: `${(item.count / max) * 100}%`,
              background: 'var(--primary)',
              borderRadius: 4,
              height: '100%',
              minWidth: item.count > 0 ? 4 : 0,
              opacity: 0.8,
              transition: 'width 0.4s ease',
            }} />
          </div>
          <div style={{ width: 28, fontSize: 12, color: 'var(--muted-foreground)', fontWeight: 500, textAlign: 'right' }}>
            {item.count}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Chart Card ──────────────────────────────────────────────────────────────

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--card)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: '20px 24px',
      flex: 1,
      minWidth: 220,
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 16, color: 'var(--foreground)' }}>{title}</div>
      {children}
    </div>
  )
}

// ─── Failed Submissions ───────────────────────────────────────────────────────

const FAILURE_BUCKETS: { key: 'hubspot' | 'nap_app' | 'missing_details'; label: string; hint: string }[] = [
  { key: 'hubspot', label: 'HubSpot rejected or unavailable', hint: 'HubSpot API returned an error or rate-limited the request — check form/field config' },
  { key: 'nap_app', label: 'NAP app error', hint: 'This app failed to complete the submission — check app logs' },
  { key: 'missing_details', label: 'Missing required details', hint: 'Conversation reached closing without enough contact info to submit' },
]

function FailureBarChart({
  failures,
  loading,
  onSelectBucket,
}: {
  failures?: AdminStats['hubspot_failures']
  loading: boolean
  onSelectBucket: (bucket: string) => void
}) {
  if (loading) {
    return <div style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>Loading…</div>
  }

  const rows = FAILURE_BUCKETS
    .map(b => ({ ...b, count: failures ? failures[b.key] : 0 }))
    .filter(r => r.count > 0)
    .sort((a, b) => b.count - a.count)

  if (rows.length === 0) {
    return (
      <div style={{ fontSize: 12, color: 'var(--muted-foreground)', padding: '4px 0' }}>
        No failed submissions — everything that reached the close is in HubSpot.
      </div>
    )
  }

  const max = Math.max(...rows.map(r => r.count), 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {rows.map(r => (
        <button
          key={r.key}
          onClick={() => onSelectBucket(r.key)}
          title={r.hint}
          style={{
            display: 'flex', alignItems: 'center', gap: 10,
            width: '100%', textAlign: 'left', padding: 0,
            border: 'none', background: 'none', cursor: 'pointer', fontFamily: 'inherit',
          }}
        >
          <div style={{ width: 168, fontSize: 12, color: 'var(--foreground)', flexShrink: 0, fontWeight: 500 }}>
            {r.label}
          </div>
          <div style={{ flex: 1, background: 'var(--muted)', borderRadius: 4, height: 18, position: 'relative', overflow: 'hidden' }}>
            <div style={{
              width: `${(r.count / max) * 100}%`,
              background: '#ef4444',
              borderRadius: 4,
              height: '100%',
              minWidth: 4,
              opacity: 0.85,
              transition: 'width 0.4s ease',
            }} />
          </div>
          <div style={{ width: 24, fontSize: 12, color: '#991b1b', fontWeight: 700, textAlign: 'right', flexShrink: 0 }}>
            {r.count}
          </div>
        </button>
      ))}
    </div>
  )
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

export default function Dashboard({ onSelectFailureBucket }: { onSelectFailureBucket?: (bucket: string) => void }) {
  const { stats, loading, error, load } = useAdminStats()

  useEffect(() => { load() }, [load])

  const hsRate = stats && stats.leads_with_contact > 0
    ? Math.round((stats.hubspot_submitted / stats.leads_with_contact) * 100)
    : 0

  const totalFailed = stats
    ? stats.hubspot_failures.hubspot + stats.hubspot_failures.nap_app + stats.hubspot_failures.missing_details
    : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {error && <div style={{ color: '#ef4444', fontSize: 13 }}>{error}</div>}

      {/* Stat cards */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <StatCard
          label="Total Conversations"
          value={loading ? '…' : (stats?.total_conversations ?? 0)}
          sub="Unique chat sessions"
        />
        <StatCard
          label="Contacts Collected"
          value={loading ? '…' : (stats?.leads_with_contact ?? 0)}
          sub="Gave name, email, phone, or company"
        />
        <StatCard
          label="HubSpot Submissions"
          value={loading ? '…' : (stats?.hubspot_submitted ?? 0)}
          sub={loading ? '' : `${hsRate}% of contacts collected`}
          tone="primary"
        />
        <StatCard
          label="Failed Submissions"
          value={loading ? '…' : totalFailed}
          sub="Never made it to HubSpot"
          tone="danger"
        />
      </div>

      {/* Failed submissions breakdown */}
      <ChartCard title="Failed Submissions by Reason">
        <FailureBarChart
          failures={stats?.hubspot_failures}
          loading={loading}
          onSelectBucket={(bucket) => onSelectFailureBucket?.(bucket)}
        />
      </ChartCard>

      {/* Monthly trend */}
      <ChartCard title="Contacts Collected — Last 6 Months">
        {loading
          ? <div style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>Loading…</div>
          : <MonthlyChart data={stats?.monthly_leads ?? []} />}
      </ChartCard>

      {/* Distribution charts */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <ChartCard title="Fleet Size Distribution">
          {loading
            ? <div style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>Loading…</div>
            : <HBarChart data={stats?.fleet_size_distribution ?? []} labelKey="range" />}
        </ChartCard>

        <ChartCard title="Camera Model Interest">
          {loading
            ? <div style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>Loading…</div>
            : <HBarChart data={stats?.camera_interest ?? []} labelKey="model" />}
        </ChartCard>

        <ChartCard title="Plan Type Interest">
          {loading
            ? <div style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>Loading…</div>
            : <HBarChart data={stats?.plan_interest ?? []} labelKey="plan" />}
        </ChartCard>
      </div>
    </div>
  )
}
