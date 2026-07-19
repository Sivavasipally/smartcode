import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class Solution {
    @GetMapping("/ganesha")
    public String getGanesha() {
        return "Om Gam Ganapathaye namaha";
    }
}
