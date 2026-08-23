import { ThinMenuWorkspace } from "@/components/menus/ThinMenuWorkspace";
import { ANALYSIS_MENU } from "@/components/menus/menuDummyData";

export default function AnalysisPage() {
  return <ThinMenuWorkspace config={ANALYSIS_MENU} />;
}
