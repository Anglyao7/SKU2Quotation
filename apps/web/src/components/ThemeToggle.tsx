import { IconButton } from "@radix-ui/themes";
import { Moon, Sun } from "@phosphor-icons/react";
import { useThemeMode } from "../context/ThemeContext";
import { useLocale } from "../core/LocaleContext";

export function ThemeToggle({
  labels,
}: {
  labels?: { toDark: string; toLight: string };
} = {}) {
  const { mode, toggle } = useThemeMode();
  const { t } = useLocale();
  return (
    <IconButton
      variant="ghost"
      color="gray"
      size="2"
      onClick={toggle}
      aria-label={
        mode === "light"
          ? labels?.toDark ?? t("切换深色模式")
          : labels?.toLight ?? t("切换浅色模式")
      }
    >
      {mode === "light" ? <Moon size={19} /> : <Sun size={19} />}
    </IconButton>
  );
}
