type PageHeaderProps = {
  title: string;
  description?: string;
};

export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight text-[var(--hirio-ink)] md:text-3xl">
        {title}
      </h1>
      {description ? (
        <p className="mt-2 max-w-2xl text-sm text-[var(--hirio-muted)] md:text-base">
          {description}
        </p>
      ) : null}
    </header>
  );
}
