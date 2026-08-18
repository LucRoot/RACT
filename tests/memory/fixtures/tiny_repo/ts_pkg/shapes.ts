/** A named entity. */
export interface Named {
  name: string;
}

/** Unique identifier alias. */
export type Id = number;

/** A colored point. */
export class Point {
  constructor(public x: number, public y: number) {}

  distance(other: Point): number {
    const dx = this.x - other.x;
    const dy = this.y - other.y;
    return Math.sqrt(dx * dx + dy * dy);
  }
}
