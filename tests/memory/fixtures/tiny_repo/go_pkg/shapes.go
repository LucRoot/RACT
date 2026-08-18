package tinyrepo

// Point is a 2D point.
type Point struct {
	X int
	Y int
}

// Shape is anything with an area.
type Shape interface {
	Area() int
}
