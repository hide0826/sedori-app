import RepricerSettingsTable from './components/RepricerSettingsTable';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4 bg-gray-50">
      <div className="w-full max-w-4xl">
        <RepricerSettingsTable />
      </div>
    </main>
  );
}
