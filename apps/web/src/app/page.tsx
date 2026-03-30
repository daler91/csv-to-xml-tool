import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold mb-4">SBA CSV to XML Converter</h1>
      <p className="text-lg text-gray-600 mb-8 text-center max-w-lg">
        Convert your SBA counseling and training CSV files to XML format.
        Preview data, map columns, validate against XSD schemas, and track
        conversion history.
      </p>
      <div className="flex gap-4">
        <Link
          href="/login"
          className="px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
        >
          Sign In
        </Link>
        <Link
          href="/signup"
          className="px-6 py-2 border border-gray-300 rounded hover:bg-gray-50 text-sm font-medium"
        >
          Create Account
        </Link>
      </div>
    </main>
  );
}
