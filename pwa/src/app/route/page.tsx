import { ThinMenuWorkspace } from "@/components/menus/ThinMenuWorkspace";
import { ROUTE_MENU } from "@/components/menus/menuDummyData";

export default function RoutePage() {
  return <ThinMenuWorkspace config={ROUTE_MENU} />;
}
