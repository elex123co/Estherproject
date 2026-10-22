import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RISK_HEX, RISK_ORDER } from "../utils/format";

const AXIS = { stroke: "#566679", fontSize: 11 } as const;
const GRID = "#1e2b3b";
const TOOLTIP = {
  contentStyle: { background: "#131d2a", border: "1px solid #2b3b50", borderRadius: 6, fontSize: 12, color: "#dbe4ee" },
  itemStyle: { color: "#dbe4ee" },
  labelStyle: { color: "#8394a7" },
  cursor: { fill: "rgba(255,255,255,0.04)" },
} as const;

export function ClassificationDonut({ normal, suspicious }: { normal: number; suspicious: number }) {
  const data = [
    { name: "Normal", value: normal, color: RISK_HEX.None },
    { name: "Suspicious", value: suspicious, color: RISK_HEX.Critical },
  ];
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={2} stroke="none">
          {data.map((d) => (
            <Cell key={d.name} fill={d.color} />
          ))}
        </Pie>
        <Tooltip {...TOOLTIP} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#8394a7" }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function RiskBars({ counts, includeNone = false }: { counts: Record<string, number>; includeNone?: boolean }) {
  const data = RISK_ORDER.filter((l) => includeNone || l !== "None").map((level) => ({ level, count: counts[level] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="level" {...AXIS} tickLine={false} />
        <YAxis {...AXIS} tickLine={false} allowDecimals={false} />
        <Tooltip {...TOOLTIP} />
        <Bar dataKey="count" name="Records" radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.level} fill={RISK_HEX[d.level]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function CategoryBars({ data }: { data: { category: string; count: number; suspicious?: boolean }[] }) {
  const height = Math.max(180, data.length * 32 + 30);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" {...AXIS} tickLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey="category" width={150} {...AXIS} tickLine={false} />
        <Tooltip {...TOOLTIP} />
        <Bar dataKey="count" name="Records" radius={[0, 4, 4, 0]}>
          {data.map((d) => (
            <Cell key={d.category} fill={d.suspicious === false ? "#3b4c60" : "#4cc2d9"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TrendChart({ data, bucket }: { data: { bucket: string; normal: number; suspicious: number }[]; bucket: "minute" | "hour" | "day" }) {
  const label = (b: string) => (bucket === "day" ? b : bucket === "hour" ? b.replace("T", " ") + ":00" : b.replace("T", " "));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="bucket" tickFormatter={(b: string) => label(b).slice(-(bucket === "day" ? 10 : 11))} {...AXIS} tickLine={false} minTickGap={24} />
        <YAxis {...AXIS} tickLine={false} allowDecimals={false} />
        <Tooltip {...TOOLTIP} labelFormatter={(b) => label(String(b))} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#8394a7" }} />
        <Bar dataKey="normal" name="Normal" stackId="a" fill={RISK_HEX.None} />
        <Bar dataKey="suspicious" name="Suspicious" stackId="a" fill={RISK_HEX.Critical} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ImportanceBars({ data }: { data: { feature: string; importance: number }[] }) {
  const height = Math.max(200, data.length * 26 + 30);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" {...AXIS} tickLine={false} tickFormatter={(v: number) => v.toFixed(2)} />
        <YAxis type="category" dataKey="feature" width={170} {...AXIS} tickLine={false} />
        <Tooltip {...TOOLTIP} formatter={(v) => Number(v).toFixed(4)} />
        <Bar dataKey="importance" name="Importance" fill="#4cc2d9" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
