import { Button, Heading, Text } from "@radix-ui/themes";
import { ArrowLeft, Compass } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Brand } from "../components/Brand";

export function NotFoundPage() {
  return (
    <main className="not-found-page">
      <Brand />
      <div className="not-found-content">
        <Compass size={42} weight="duotone" />
        <Heading size="7">页面没有找到</Heading>
        <Text color="gray">链接可能已失效，或你没有访问这个页面的权限。</Text>
        <Button asChild><Link to="/"><ArrowLeft size={17} />返回官网</Link></Button>
      </div>
    </main>
  );
}
