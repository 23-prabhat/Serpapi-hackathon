import { CheckDetail } from "@/components/check-detail";

export default async function CheckPage(props: PageProps<"/checks/[checkId]">) {
  const { checkId } = await props.params;
  return <CheckDetail checkId={checkId} />;
}
