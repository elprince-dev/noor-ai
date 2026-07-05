"use client";

import { School } from "@/lib/api";

interface SchoolSelectorProps {
  value: School;
  onChange: (school: School) => void;
}

const SCHOOLS: { value: School; label: string }[] = [
  { value: "general", label: "All Schools" },
  { value: "hanafi", label: "Hanafi" },
  { value: "maliki", label: "Maliki" },
  { value: "shafii", label: "Shafi'i" },
  { value: "hanbali", label: "Hanbali" },
];

export function SchoolSelector({ value, onChange }: SchoolSelectorProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as School)}
      className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
    >
      {SCHOOLS.map((school) => (
        <option key={school.value} value={school.value}>
          {school.label}
        </option>
      ))}
    </select>
  );
}
