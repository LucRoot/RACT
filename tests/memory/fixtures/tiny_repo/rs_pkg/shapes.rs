/// A 2D point.
pub struct Point {
    pub x: i32,
    pub y: i32,
}

/// A cardinal direction.
pub enum Direction {
    North,
    South,
    East,
    West,
}

/// Anything that can greet.
pub trait Greet {
    fn greet(&self) -> String;
}
