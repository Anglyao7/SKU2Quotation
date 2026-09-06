import { Badge, Button, Card, Flex, Spinner, Switch, Text, TextField } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";
import type { StorefrontLocale } from "../../types";
import { getCatalogTranslationAutomation, updateCatalogTranslationAutomation, type CatalogTranslationAutomation } from "../api";
import { useLocale } from "../LocaleContext";
import { automaticTranslationCopy } from "../automationMessages";

export function AutomaticTranslationControls({ tenantId, targetLocale, canEdit, onStatus }: {
  tenantId: string; targetLocale: StorefrontLocale; canEdit: boolean;
  onStatus: (status: CatalogTranslationAutomation | undefined) => void;
}) {
  const { locale } = useLocale();
  const copy = automaticTranslationCopy(locale);
  const [status, setStatus] = useState<CatalogTranslationAutomation>();
  const [enabled, setEnabled] = useState(false);
  const [publish, setPublish] = useState(false);
  const [delay, setDelay] = useState("30");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const dirty = useRef(false);
  const callback = useRef(onStatus);
  const mounted = useRef(false);
  callback.current = onStatus;
  useEffect(() => {
    let alive = true;
    mounted.current = true;
    let busy = false;
    callback.current(undefined);
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const next = await getCatalogTranslationAutomation(targetLocale, tenantId);
        if (!alive) return;
        setStatus(next);
        setError("");
        callback.current(next);
        if (!dirty.current) {
          setEnabled(next.enabled); setPublish(next.auto_publish); setDelay(String(next.debounce_seconds));
        }
      } catch {
        if (alive) { setStatus(undefined); setError(copy.failure); callback.current(undefined); }
      } finally { busy = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 5000);
    return () => { alive = false; mounted.current = false; window.clearInterval(timer); };
  }, [tenantId, targetLocale, copy.failure]);
  const save = async () => {
    setSaving(true); setError("");
    try {
      const next = await updateCatalogTranslationAutomation(targetLocale, tenantId, {
        enabled, auto_publish: publish, debounce_seconds: Number(delay),
      });
      if (!mounted.current) return;
      dirty.current = false;
      setStatus(next); callback.current(next);
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : copy.failure); }
    finally { if (mounted.current) setSaving(false); }
  };
  const working = status && ["RUNNING", "QUEUED", "WAITING"].includes(status.state);
  return <Card>
    <Flex direction="column" gap="3">
      <Flex align="center" justify="between" gap="3" wrap="wrap">
        <Text weight="bold">{copy.title}</Text>
        <Badge color={working ? "blue" : status?.state === "ATTENTION" ? "amber" : "green"} role="status" aria-live="polite">
          {!status || working ? <Spinner size="1" /> : null}
          {!status ? copy.loading : status.active_job_origin === "MANUAL" && working ? copy.manual : copy[status.state]}
        </Badge>
      </Flex>
      <Text size="1" color="gray">{copy.help}</Text>
      <Flex gap="5" align="center" wrap="wrap">
        <Text as="label" size="2"><Flex gap="2" align="center"><Switch checked={enabled} disabled={!status || !canEdit || saving} onCheckedChange={value => { dirty.current = true; setEnabled(value); }} />{copy.enabled}</Flex></Text>
        <Text as="label" size="2"><Flex gap="2" align="center"><Switch checked={publish} disabled={!status || !canEdit || saving} onCheckedChange={value => { dirty.current = true; setPublish(value); }} />{copy.publish}</Flex></Text>
        <Text as="label" size="2"><Flex gap="2" align="center">{copy.delay}<TextField.Root aria-label={copy.delay} type="number" min={5} max={600} value={delay} style={{ width: 90 }} disabled={!status || !canEdit || saving} onChange={event => { dirty.current = true; setDelay(event.target.value); }} /></Flex></Text>
        <Button onClick={() => void save()} loading={saving} disabled={!status || !canEdit || !dirty.current || !Number.isInteger(Number(delay)) || Number(delay) < 5 || Number(delay) > 600}>{copy.save}</Button>
      </Flex>
      {error || status?.last_error ? <Text color="red" size="2">{error || status?.last_error}</Text> : null}
    </Flex>
  </Card>;
}
