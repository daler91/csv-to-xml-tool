/**
 * Shared Card primitive.
 *
 * A thin wrapper around the "white bg, gray border, rounded,
 * padding" combo that appears dozens of times across the app.
 * Resolves UX_REVIEW.md §8.1 for cards.
 */

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function Card({
  children,
  className = "",
  ...rest
}: Readonly<CardProps>) {
  return (
    <div
      className={`bg-white border border-gray-200 rounded p-4 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
