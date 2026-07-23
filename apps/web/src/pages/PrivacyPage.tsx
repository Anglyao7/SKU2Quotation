import { ArrowLeft } from "@phosphor-icons/react";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Brand } from "../components/Brand";

const operatorName = String(
  import.meta.env.VITE_LEGAL_OPERATOR_NAME || "澄湾选品运营方",
).trim();
const privacyContactEmail = String(
  import.meta.env.VITE_PRIVACY_CONTACT_EMAIL || "",
).trim();
const effectiveDate = String(
  import.meta.env.VITE_PRIVACY_EFFECTIVE_DATE || "2026-07-23",
).trim();

export function PrivacyPage() {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "隐私政策 | 澄湾选品";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <main className="legal-page">
      <header className="legal-header">
        <Brand subtitle="万千货品，自成脉络" />
        <Link to="/" className="legal-back"><ArrowLeft size={17} />返回首页</Link>
      </header>

      <article className="legal-document">
        <div className="legal-title">
          <span>PRIVACY</span>
          <h1>隐私政策</h1>
          <p>生效日期：{effectiveDate}</p>
        </div>

        <p className="legal-lead">
          本政策说明 {operatorName}（“平台运营者”）如何处理你在澄湾选品官网、商家商品前台与报价流程中提供的个人信息。
          商家通过其专属前台独立接收并处理报价需求时，也应履行相应的个人信息保护义务。
        </p>

        <section>
          <h2>一、我们处理哪些信息</h2>
          <p>当你浏览公开商品时，我们会处理保障网站运行所必需的网络日志与安全信息。搜索、筛选与普通浏览不要求你创建账号。</p>
          <p>当你生成报价草稿时，我们会处理你主动填写的姓名、公司、邮箱或电话、报价备注，以及你选择的 SKU、数量、生成时间和当时确认的隐私政策版本。请不要在备注中填写身份证件、金融账户、健康状况等与报价无关的敏感信息。</p>
          <p>商家成员登录工作台时，身份服务会处理账号标识、已验证邮箱、登录时间、会话与安全验证信息；访问权限由所属商家和角色共同决定。</p>
        </section>

        <section>
          <h2>二、处理目的与使用方式</h2>
          <p>上述信息仅用于展示商品、响应搜索、生成和下载报价草稿、联系你确认交易条件、维护账号与租户权限、预防滥用、排查故障及履行法定义务。我们不会把公开报价草稿直接视为已经确认的订单或正式商业承诺。</p>
        </section>

        <section>
          <h2>三、信息提供、委托处理与租户边界</h2>
          <p>你在某一商家前台提交的报价信息会提供给该商家，用于处理本次询价。平台可能委托服务器、对象存储、身份认证、邮件或安全服务供应商提供必要的技术处理，并通过合同与权限控制限制其用途。</p>
          <p>平台按商家隔离业务数据；普通商家成员不能访问其他商家的商品、客户信息或报价。除非取得你的单独同意或法律另有规定，我们不会出售个人信息，也不会将其用于与本次服务无关的营销。</p>
        </section>

        <section>
          <h2>四、保存期限与安全措施</h2>
          <p>我们仅在完成报价跟进、履行合同、处理争议与满足法定留存义务所必需的期间保存信息；目的实现且无继续保存依据后，将删除或匿名化处理。具体期限难以预先确定时，以客户关系状态、报价有效期、争议处理期限及适用法律要求作为判断标准。</p>
          <p>我们采用 HTTPS、最小权限、租户隔离、数据库行级策略、登录多因素验证、访问限速、文件扫描与备份校验等措施降低未经授权访问、泄露、篡改或丢失的风险。</p>
        </section>

        <section>
          <h2>五、你的权利</h2>
          <p>你可以请求查阅、复制、更正、补充或删除个人信息，也可以对处理规则提出解释请求。若你希望撤回非必要处理的同意、注销账号或对报价信息提出异议，请通过下方邮箱联系我们，并提供足以定位记录且不过度暴露身份的信息。</p>
        </section>

        <section>
          <h2>六、未成年人</h2>
          <p>本服务面向企业采购、供应与销售人员，不以未满十四周岁的未成年人为目标用户。如我们发现误收相关信息，将在核实后尽快删除。</p>
        </section>

        <section>
          <h2>七、政策更新与联系我们</h2>
          <p>当处理目的、信息类型或服务方式发生实质变化时，我们会更新本政策，并在需要时重新取得你的授权。</p>
          <p>
            个人信息处理者：{operatorName}<br />
            隐私联系邮箱：{privacyContactEmail
              ? <a href={`mailto:${privacyContactEmail}`}>{privacyContactEmail}</a>
              : "生产上线前配置并公示"}
          </p>
        </section>
      </article>
    </main>
  );
}
