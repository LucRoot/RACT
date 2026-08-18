package tinyrepo

// Greeter is a polite Go greeter.
type Greeter struct {
	Name string
}

// Greet returns a greeting.
func (g Greeter) Greet() string {
	return "Hello, " + g.Name
}
