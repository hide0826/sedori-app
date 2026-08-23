import { ThinMenuWorkspace } from "@/components/menus/ThinMenuWorkspace";
import { DATABASE_MENU } from "@/components/menus/menuDummyData";

export default function DatabasePage() {
  return <ThinMenuWorkspace config={DATABASE_MENU} />;
}
