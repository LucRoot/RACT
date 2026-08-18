/** A polite greeter written in TypeScript. */
export class Greeter {
  greet(name: string): string {
    return `Hello, ${name}`;
  }
}

/** Factory that returns a fresh Greeter. */
export function makeGreeter(): Greeter {
  return new Greeter();
}

/** Arrow function assigned to a const at module scope. */
export const shout = (name: string): string => `HELLO, ${name.toUpperCase()}`;
