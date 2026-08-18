/// A polite greeter written in Rust.
pub struct Greeter {
    pub name: String,
}

impl Greeter {
    /// Construct a greeter that will address ``name``.
    pub fn new(name: String) -> Self {
        Greeter { name }
    }

    /// Return a greeting.
    pub fn greet(&self) -> String {
        format!("Hello, {}", self.name)
    }
}
