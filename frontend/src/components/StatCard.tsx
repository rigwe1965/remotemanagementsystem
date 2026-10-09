interface StatCardProps {
  title: string;
  value: number | string;
  sub?: string;
  icon: React.ReactNode;
  color?: 'default' | 'green' | 'red' | 'yellow' | 'blue';
}

const COLOR_MAP = {
  default: 'bg-white border-gray-100',
  green:   'bg-white border-green-100',
  red:     'bg-white border-red-100',
  yellow:  'bg-white border-amber-100',
  blue:    'bg-white border-sky-100',
};

const ICON_MAP = {
  default: 'bg-gray-50 text-gray-500',
  green:   'bg-green-50 text-green-600',
  red:     'bg-red-50 text-red-500',
  yellow:  'bg-amber-50 text-amber-600',
  blue:    'bg-sky-50 text-sky-600',
};

export default function StatCard({ title, value, sub, icon, color = 'default' }: StatCardProps) {
  return (
    <div className={`rounded-xl border p-5 shadow-xs flex items-start gap-4 ${COLOR_MAP[color]}`}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${ICON_MAP[color]}`}>
        {icon}
      </div>
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{title}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}
