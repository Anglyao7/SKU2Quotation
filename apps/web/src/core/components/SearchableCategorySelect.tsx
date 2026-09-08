import { Button, Popover, TextField } from "@radix-ui/themes";
import { CaretDown, Check, MagnifyingGlass } from "@phosphor-icons/react";
import { useState } from "react";
import { useLocale } from "../LocaleContext";

export function SearchableCategorySelect({ value, onChange, options, placeholder, label, disabled = false }: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ id: string; label: string }>;
  placeholder: string;
  label: string;
  disabled?: boolean;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = options.find((option) => option.id === value);
  const filtered = options.filter((option) => option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const choose = (id: string) => { onChange(id); setOpen(false); };
  return <Popover.Root open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQuery(""); }}>
    <Popover.Trigger>
      <Button type="button" variant="surface" color="gray" disabled={disabled} className="admin-category-trigger" aria-label={label}>
        <span title={selected?.label}>{selected?.label || placeholder}</span><CaretDown />
      </Button>
    </Popover.Trigger>
    <Popover.Content className="admin-category-popover" align="start" sideOffset={6}>
      <TextField.Root value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("搜索分类")} aria-label={t("搜索分类")}>
        <TextField.Slot><MagnifyingGlass /></TextField.Slot>
      </TextField.Root>
      <div className="admin-category-options" aria-label={label}>
        <button type="button" onClick={() => choose("")} aria-pressed={!value}><span>{placeholder}</span>{!value ? <Check /> : null}</button>
        {filtered.map((option) => <button type="button" key={option.id} onClick={() => choose(option.id)} aria-pressed={value === option.id}>
          <span>{option.label}</span>{value === option.id ? <Check /> : null}
        </button>)}
        {!filtered.length ? <p>{t("没有匹配的分类")}</p> : null}
      </div>
    </Popover.Content>
  </Popover.Root>;
}
