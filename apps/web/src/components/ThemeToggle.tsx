import { IconButton, Tooltip } from "@radix-ui/themes";
import { Moon, Sun } from "@phosphor-icons/react";
import { useThemeMode } from "../context/ThemeContext";

export function ThemeToggle() {
  const { mode, toggle } = useThemeMode();
  return (
    <Tooltip content={mode === "light" ? "切换深色模式" : "切换浅色模式"}>
      <IconButton variant="ghost" color="gray" size="2" onClick={toggle} aria-label="切换显示模式">
        {mode === "light" ? <Moon size={19} /> : <Sun size={19} />}
      </IconButton>
    </Tooltip>
  );
}
